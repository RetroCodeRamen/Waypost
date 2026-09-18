"""SQLite Commons store — local social feed until Memos adapter lands."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from shared.protocol.envelope import new_id


COMMONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS commons_posts (
    id TEXT PRIMARY KEY,
    author TEXT NOT NULL COLLATE NOCASE,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commons_created
    ON commons_posts(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_commons_author
    ON commons_posts(author, created_at DESC);
"""


class CommonsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(COMMONS_SCHEMA)
        self._conn.commit()

    def create(
        self,
        *,
        author: str,
        body: str,
        title: str = "",
        post_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        pid = post_id or new_id()
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO commons_posts (id, author, title, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pid, author, title or "", body, ts),
        )
        self._conn.commit()
        return self.get(pid)  # type: ignore[return-value]

    def get(self, post_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM commons_posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        return self._row(row) if row else None

    def list_posts(self, *, limit: int = 50, since: Optional[float] = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        if since is not None:
            rows = self._conn.execute(
                """
                SELECT * FROM commons_posts
                WHERE created_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (float(since), limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM commons_posts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def count_recent(self, *, since: float, exclude_author: Optional[str] = None) -> int:
        if exclude_author:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM commons_posts
                WHERE created_at > ? AND author != ? COLLATE NOCASE
                """,
                (since, exclude_author),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM commons_posts
                WHERE created_at > ?
                """,
                (since,),
            ).fetchone()
        return int(row["n"])

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "author": row["author"],
            "title": row["title"] or "",
            "body": row["body"],
            "created_at": row["created_at"],
        }
