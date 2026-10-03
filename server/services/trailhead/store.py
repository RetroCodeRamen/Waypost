"""SQLite Trailhead store — small linked text pages, current version only."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

TRAILHEAD_SCHEMA = """
CREATE TABLE IF NOT EXISTS trailhead_pages (
    path TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_by TEXT NOT NULL COLLATE NOCASE,
    updated_at REAL NOT NULL
);
"""


class TrailheadStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(TRAILHEAD_SCHEMA)
        self._conn.commit()

    def get_page(self, path: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT path, title, body, updated_by, updated_at FROM trailhead_pages WHERE path = ?",
            (path,),
        ).fetchone()
        return self._row(row) if row else None

    def list_pages(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT path, title, length(body) AS size, updated_by, updated_at
              FROM trailhead_pages ORDER BY path
            """
        ).fetchall()
        return [
            {
                "path": r[0],
                "title": r[1],
                "size": r[2],
                "updated_by": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]

    def count_pages(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM trailhead_pages").fetchone()[0])

    def put_page(self, *, path: str, title: str, body: str, author: str) -> dict[str, Any]:
        self._conn.execute(
            """
            INSERT INTO trailhead_pages (path, title, body, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title = excluded.title,
                body = excluded.body,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (path, title, body, author, time.time()),
        )
        self._conn.commit()
        return self.get_page(path)  # type: ignore[return-value]

    def delete_page(self, path: str) -> bool:
        cur = self._conn.execute("DELETE FROM trailhead_pages WHERE path = ?", (path,))
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "path": row[0],
            "title": row[1],
            "body": row[2],
            "updated_by": row[3],
            "updated_at": row[4],
        }
