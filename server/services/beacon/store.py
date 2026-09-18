"""SQLite Beacon store — emergency alerts (distinct from Noticeboard)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from shared.protocol.envelope import new_id


BEACON_SCHEMA = """
CREATE TABLE IF NOT EXISTS beacons (
    id TEXT PRIMARY KEY,
    author TEXT NOT NULL COLLATE NOCASE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'emergency',
    created_at REAL NOT NULL,
    cleared_at REAL,
    active INTEGER NOT NULL DEFAULT 1,
    mid TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_beacons_active
    ON beacons(active, created_at DESC);
"""


class BeaconStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(BEACON_SCHEMA)
        self._conn.commit()

    def push(
        self,
        *,
        author: str,
        title: str,
        body: str,
        severity: str = "emergency",
        beacon_id: Optional[str] = None,
        mid: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        if mid:
            existing = self._conn.execute(
                "SELECT * FROM beacons WHERE mid = ?", (mid,)
            ).fetchone()
            if existing:
                return self._row(existing)

        bid = beacon_id or new_id()
        ts = created_at if created_at is not None else time.time()
        # New active beacon: clear previous actives (one primary emergency at a time)
        self._conn.execute(
            "UPDATE beacons SET active = 0, cleared_at = ? WHERE active = 1",
            (ts,),
        )
        self._conn.execute(
            """
            INSERT INTO beacons
                (id, author, title, body, severity, created_at, cleared_at, active, mid)
            VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?)
            """,
            (bid, author, title, body, severity, ts, mid),
        )
        self._conn.commit()
        return self.get(bid)  # type: ignore[return-value]

    def get(self, beacon_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM beacons WHERE id = ?", (beacon_id,)
        ).fetchone()
        return self._row(row) if row else None

    def get_active(self) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            """
            SELECT * FROM beacons WHERE active = 1
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        return self._row(row) if row else None

    def list_beacons(self, *, limit: int = 20, active_only: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        if active_only:
            rows = self._conn.execute(
                """
                SELECT * FROM beacons WHERE active = 1
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM beacons
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def clear(self, beacon_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        now = time.time()
        if beacon_id:
            self._conn.execute(
                """
                UPDATE beacons SET active = 0, cleared_at = ?
                WHERE id = ? AND active = 1
                """,
                (now, beacon_id),
            )
            self._conn.commit()
            return self.get(beacon_id)
        row = self.get_active()
        if not row:
            return None
        self._conn.execute(
            """
            UPDATE beacons SET active = 0, cleared_at = ?
            WHERE id = ?
            """,
            (now, row["id"]),
        )
        self._conn.commit()
        return self.get(row["id"])

    def last_push_at(self, author: str) -> Optional[float]:
        row = self._conn.execute(
            """
            SELECT created_at FROM beacons
            WHERE author = ? COLLATE NOCASE
            ORDER BY created_at DESC LIMIT 1
            """,
            (author,),
        ).fetchone()
        return float(row["created_at"]) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "author": row["author"],
            "title": row["title"],
            "body": row["body"],
            "severity": row["severity"],
            "created_at": row["created_at"],
            "cleared_at": row["cleared_at"],
            "active": bool(row["active"]),
            "mid": row["mid"],
        }
