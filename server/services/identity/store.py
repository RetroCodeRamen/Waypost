"""SQLite store for identities and the certificates Station has issued.

All three certificate kinds share one serial space (``certs.serial``). Only
the fields are stored: signatures are recomputed when served (Ed25519 is
deterministic, so a certificate is always served with the same bytes).
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Optional

IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    identity_id BLOB NOT NULL UNIQUE,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS certs (
    serial INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- id | dev | rev
    username TEXT COLLATE NOCASE,
    identity_id BLOB,
    display_name TEXT,                  -- id
    node_id TEXT,                       -- dev
    signing_key BLOB,                   -- dev
    device_hash BLOB,                   -- dev
    revokes INTEGER,                    -- rev: the serial it revokes
    issued INTEGER NOT NULL,
    expires INTEGER,                    -- id, dev
    revoked_at INTEGER                  -- id, dev: set when revoked
);
CREATE INDEX IF NOT EXISTS certs_user ON certs (kind, username);
CREATE INDEX IF NOT EXISTS certs_node ON certs (kind, node_id);
"""


class IdentityStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(IDENTITY_SCHEMA)
        self._conn.commit()

    # -- identities ---------------------------------------------------------

    def identity_id(self, username: str) -> bytes:
        """The person's stable identity id, created on first use."""
        row = self._conn.execute(
            "SELECT identity_id FROM identities WHERE username = ?", (username,)
        ).fetchone()
        if row:
            return bytes(row[0])
        ident = os.urandom(16)
        self._conn.execute(
            "INSERT INTO identities (username, identity_id, created_at) VALUES (?, ?, ?)",
            (username, ident, time.time()),
        )
        self._conn.commit()
        return ident

    # -- certificates -------------------------------------------------------

    def _insert(self, **fields: Any) -> dict[str, Any]:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._conn.execute(f"INSERT INTO certs ({cols}) VALUES ({marks})", tuple(fields.values()))
        self._conn.commit()
        return self.get(int(cur.lastrowid))

    def get(self, serial: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM certs WHERE serial = ?", (serial,)).fetchone()
        return dict(row) if row else None

    def add_identity(self, *, username: str, identity_id: bytes, display_name: str,
                     issued: int, expires: int) -> dict[str, Any]:
        return self._insert(kind="id", username=username, identity_id=identity_id,
                            display_name=display_name, issued=issued, expires=expires)

    def add_device(self, *, username: str, identity_id: bytes, node_id: str, signing_key: bytes,
                   device_hash: bytes, issued: int, expires: int) -> dict[str, Any]:
        return self._insert(kind="dev", username=username, identity_id=identity_id, node_id=node_id,
                            signing_key=signing_key, device_hash=device_hash, issued=issued,
                            expires=expires)

    def latest_identity(self, username: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            """SELECT * FROM certs WHERE kind = 'id' AND username = ? AND revoked_at IS NULL
               ORDER BY serial DESC LIMIT 1""",
            (username,),
        ).fetchone()
        return dict(row) if row else None

    def device_certs(self, username: str, now: int) -> list[dict[str, Any]]:
        """Unrevoked, unexpired device certificates — newest per device."""
        rows = self._conn.execute(
            """SELECT * FROM certs WHERE kind = 'dev' AND username = ? AND revoked_at IS NULL
               AND expires > ? ORDER BY serial DESC""",
            (username, now),
        ).fetchall()
        seen: set[tuple[str, bytes]] = set()
        out = []
        for r in rows:
            key = (r["node_id"], bytes(r["signing_key"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(r))
        out.reverse()  # oldest first: stable indexes for paging
        return out

    def live_device_certs(self, now: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM certs WHERE kind = 'dev' AND revoked_at IS NULL AND expires > ?", (now,)
        ).fetchall()
        return [dict(r) for r in rows]

    def certs_for_node(self, node_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM certs WHERE kind = 'dev' AND node_id = ? AND revoked_at IS NULL", (node_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def revoke(self, serial: int, now: int) -> Optional[dict[str, Any]]:
        """Marks `serial` revoked and records a revocation certificate."""
        cur = self._conn.execute(
            "UPDATE certs SET revoked_at = ? WHERE serial = ? AND revoked_at IS NULL", (now, serial)
        )
        if cur.rowcount == 0:
            self._conn.commit()
            return None
        return self._insert(kind="rev", revokes=serial, issued=now)

    def revocations(self, now: int) -> list[dict[str, Any]]:
        """Revocations still worth spreading: the revoked certificate hasn't
        expired yet (after that nobody accepts it anyway)."""
        rows = self._conn.execute(
            """SELECT r.* FROM certs r JOIN certs c ON c.serial = r.revokes
               WHERE r.kind = 'rev' AND c.expires > ? ORDER BY r.serial""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
