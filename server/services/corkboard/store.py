"""SQLite Corkboard store — per-outpost public note board.

The Outpost's own copy is the durable primary; Station's is backup — sync
never clears the Outpost's copy (unlike Dispatch's courier queue, where the
local copy is just a delivery vehicle). Reads are always scoped to one
outpost_id; there is no cross-outpost query, by design (bounded UX/security
blast radius — see docs/architecture.md).
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from shared.protocol.envelope import new_id


CORKBOARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS outposts (
    node_id TEXT PRIMARY KEY,
    display_name TEXT,
    transport_dest TEXT,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS corkboard_notes (
    id TEXT PRIMARY KEY,
    outpost_id TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT,
    created_at REAL NOT NULL,
    synced_at REAL
);

CREATE INDEX IF NOT EXISTS idx_corkboard_notes_outpost
    ON corkboard_notes(outpost_id, created_at DESC);

CREATE TABLE IF NOT EXISTS corkboard_outbox (
    id TEXT PRIMARY KEY,
    outpost_id TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_corkboard_outbox_outpost
    ON corkboard_outbox(outpost_id, created_at ASC);
"""


class CorkboardStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(CORKBOARD_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cols = {
            r[1] for r in self._conn.execute("PRAGMA table_info(outposts)").fetchall()
        }
        if "transport_dest" not in cols:
            self._conn.execute("ALTER TABLE outposts ADD COLUMN transport_dest TEXT")

    # -- Outpost registry --

    def touch_outpost(
        self,
        node_id: str,
        *,
        display_name: Optional[str] = None,
        transport_dest: Optional[str] = None,
    ) -> dict[str, Any]:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO outposts (node_id, display_name, transport_dest, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, outposts.display_name),
                transport_dest = COALESCE(excluded.transport_dest, outposts.transport_dest),
                last_seen_at = excluded.last_seen_at
            """,
            (node_id, display_name, transport_dest, now, now),
        )
        self._conn.commit()
        return self.get_outpost(node_id)  # type: ignore[return-value]

    def list_claimed_outposts(self) -> list[dict[str, Any]]:
        """Outposts with a known Reticulum destination — what Station
        should re-teach the transport at startup (mirrors device_bindings'
        transport_dest rehydration in server/api/main.py)."""
        rows = self._conn.execute(
            "SELECT * FROM outposts WHERE transport_dest IS NOT NULL AND transport_dest != ''"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_outpost(self, node_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM outposts WHERE node_id = ?", (node_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_outposts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM outposts ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Notes (Outpost's own backed-up copy) --

    def add_note(
        self,
        *,
        outpost_id: str,
        body: str,
        signature: Optional[str],
        note_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> tuple[dict[str, Any], bool]:
        nid = note_id or new_id()
        existing = self._conn.execute(
            "SELECT * FROM corkboard_notes WHERE id = ?", (nid,)
        ).fetchone()
        if existing:
            return dict(existing), False
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO corkboard_notes (id, outpost_id, body, signature, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nid, outpost_id, body, signature, ts),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM corkboard_notes WHERE id = ?", (nid,)
        ).fetchone()
        return dict(row), True

    def list_notes(self, outpost_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM corkboard_notes
            WHERE outpost_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (outpost_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_unsynced(self, outpost_id: str) -> list[dict[str, Any]]:
        """Outpost-side only: this outpost's own notes it hasn't yet
        confirmed reached Station. `synced_at` is meaningless on Station's
        own copy (every note there arrived already-synced, by definition)."""
        rows = self._conn.execute(
            """
            SELECT * FROM corkboard_notes
            WHERE outpost_id = ? AND synced_at IS NULL
            ORDER BY created_at ASC
            """,
            (outpost_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_synced(self, note_id: str) -> None:
        self._conn.execute(
            "UPDATE corkboard_notes SET synced_at = ? WHERE id = ?",
            (time.time(), note_id),
        )
        self._conn.commit()

    # -- Outbox (Station-composed, queued for a specific outpost) --

    def queue_outbox(
        self,
        *,
        outpost_id: str,
        body: str,
        signature: Optional[str],
        note_id: Optional[str] = None,
    ) -> dict[str, Any]:
        nid = note_id or new_id()
        ts = time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO corkboard_outbox
                (id, outpost_id, body, signature, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nid, outpost_id, body, signature, ts),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM corkboard_outbox WHERE id = ?", (nid,)
        ).fetchone()
        return dict(row)

    def list_outbox(self, outpost_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM corkboard_outbox
            WHERE outpost_id = ?
            ORDER BY created_at ASC
            """,
            (outpost_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_outbox(self, note_id: str) -> None:
        self._conn.execute("DELETE FROM corkboard_outbox WHERE id = ?", (note_id,))
        self._conn.commit()
