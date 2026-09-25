"""SQLite Rollcall store — presence/status, separate from user identity.

Owns the `presence` table the same way BeaconStore/CommonsStore own theirs:
constructed with the shared connection, migrates its own schema at
construction time. Previously this table was built by RollcallService's
private `_ensure_schema()`, bypassing Database's centralized SCHEMA/
_migrate() -- the one other place table definitions live.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

PRESENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS presence (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    status TEXT NOT NULL DEFAULT '',
    last_seen REAL,
    via TEXT
);
"""


class RollcallStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(PRESENCE_SCHEMA)
        self._conn.commit()

    def get_presence(self, username: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT status, last_seen, via FROM presence WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_presence(
        self, username: str, *, status: str, last_seen: float, via: str
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO presence (username, status, last_seen, via)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                status = excluded.status,
                last_seen = excluded.last_seen,
                via = excluded.via
            """,
            (username, status, last_seen, via),
        )
        self._conn.commit()
