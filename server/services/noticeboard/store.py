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

CREATE TABLE IF NOT EXISTS notice_acks (
    notice_id TEXT NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    acked_at REAL NOT NULL,
    PRIMARY KEY (notice_id, username)
);
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

    def get(self, notice_id: str, *, username: Optional[str] = None) -> Optional[dict[str, Any]]:
        self._expire_due()
        row = self._conn.execute(
            "SELECT * FROM notices WHERE id = ?",
            (notice_id,),
        ).fetchone()
        if not row:
            return None
        acked = username is not None and notice_id in self.acked_ids_for(username)
        return self._row(row, acked=acked)

    def list_notices(
        self,
        *,
        active_only: bool = True,
        limit: int = 50,
        username: Optional[str] = None,
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
        acked_ids = self.acked_ids_for(username) if username is not None else set()
        return [self._row(r, acked=r["id"] in acked_ids) for r in rows]

    def ack(self, notice_id: str, username: str) -> None:
        self._conn.execute(
            """
            INSERT INTO notice_acks (notice_id, username, acked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(notice_id, username) DO NOTHING
            """,
            (notice_id, username, time.time()),
        )
        self._conn.commit()

    def acked_ids_for(self, username: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT notice_id FROM notice_acks WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchall()
        return {r["notice_id"] for r in rows}

    def count_unacked_active(self, username: str) -> int:
        self._expire_due()
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM notices
            WHERE active = 1
              AND id NOT IN (
                  SELECT notice_id FROM notice_acks WHERE username = ? COLLATE NOCASE
              )
            """,
            (username,),
        ).fetchone()
        return int(row["n"])

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
    def _row(row: sqlite3.Row, *, acked: Optional[bool] = None) -> dict[str, Any]:
        out = {
            "id": row["id"],
            "author": row["author"],
            "title": row["title"],
            "body": row["body"],
            "priority": row["priority"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "active": bool(row["active"]),
        }
        # Only present when a username was given to annotate against — a
        # global/anonymous read (no username) shouldn't imply "unacked by
        # nobody in particular".
        if acked is not None:
            out["acked"] = acked
        return out
