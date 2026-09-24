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
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(commons_posts)").fetchall()
        }
        if "group_id" not in cols:
            self._conn.execute("ALTER TABLE commons_posts ADD COLUMN group_id TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_commons_group ON commons_posts(group_id)"
        )

    def create(
        self,
        *,
        author: str,
        body: str,
        title: str = "",
        post_id: Optional[str] = None,
        created_at: Optional[float] = None,
        group_id: Optional[str] = None,
    ) -> dict[str, Any]:
        pid = post_id or new_id()
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO commons_posts (id, author, title, body, created_at, group_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pid, author, title or "", body, ts, group_id),
        )
        self._conn.commit()
        return self.get(pid)  # type: ignore[return-value]

    def get(self, post_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM commons_posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        return self._row(row) if row else None

    def list_posts(
        self,
        *,
        limit: int = 50,
        since: Optional[float] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        group_clause = " AND group_id = ?" if group_id else ""
        if since is not None:
            params: list[Any] = [float(since)]
            if group_id:
                params.append(group_id)
            params.append(limit)
            rows = self._conn.execute(
                f"""
                SELECT * FROM commons_posts
                WHERE created_at > ?{group_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            params = []
            if group_id:
                params.append(group_id)
            params.append(limit)
            rows = self._conn.execute(
                f"""
                SELECT * FROM commons_posts
                WHERE 1=1{group_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row(r) for r in rows]

    def count_recent(
        self,
        *,
        since: float,
        exclude_author: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> int:
        clauses = ["created_at > ?"]
        params: list[Any] = [since]
        if exclude_author:
            clauses.append("author != ? COLLATE NOCASE")
            params.append(exclude_author)
        if group_id:
            clauses.append("group_id = ?")
            params.append(group_id)
        row = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM commons_posts WHERE {' AND '.join(clauses)}",
            params,
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
            "group_id": row["group_id"] if "group_id" in row.keys() else None,
        }
