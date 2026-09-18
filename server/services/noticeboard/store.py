"""SQLite Noticeboard store — structured community bulletins."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from shared.protocol.envelope import new_id


NOTICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id TEXT PRIMARY KEY,
    author TEXT NOT NULL COLLATE NOCASE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    created_at REAL NOT NULL,
    expires_at REAL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_notices_active
    ON notices(active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notices_expires
    ON notices(expires_at);
"""


class NoticeStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(NOTICE_SCHEMA)
        self._conn.commit()

    def create(
        self,
        *,
        author: str,
        title: str,
        body: str,
        priority: str = "normal",
        expires_at: Optional[float] = None,
        notice_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        nid = notice_id or new_id()
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO notices
                (id, author, title, body, priority, created_at, expires_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (nid, author, title, body, priority, ts, expires_at),
        )
        self._conn.commit()
        return self.get(nid)  # type: ignore[return-value]

    def get(self, notice_id: str) -> Optional[dict[str, Any]]:
        self._expire_due()
        row = self._conn.execute(
            "SELECT * FROM notices WHERE id = ?",
            (notice_id,),
        ).fetchone()
        return self._row(row) if row else None

    def list_notices(
        self,
        *,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._expire_due()
        limit = max(1, min(int(limit), 200))
        if active_only:
            rows = self._conn.execute(
                """
                SELECT * FROM notices
                WHERE active = 1
                ORDER BY
                    CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM notices
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def expire(self, notice_id: str) -> Optional[dict[str, Any]]:
        self._conn.execute(
            "UPDATE notices SET active = 0 WHERE id = ?",
            (notice_id,),
        )
        self._conn.commit()
        return self.get(notice_id)

    def count_active(self) -> int:
        self._expire_due()
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM notices WHERE active = 1"
        ).fetchone()
        return int(row["n"])

    def _expire_due(self) -> None:
        now = time.time()
        self._conn.execute(
            """
            UPDATE notices SET active = 0
            WHERE active = 1 AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (now,),
        )
        self._conn.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "author": row["author"],
            "title": row["title"],
            "body": row["body"],
            "priority": row["priority"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "active": bool(row["active"]),
        }
