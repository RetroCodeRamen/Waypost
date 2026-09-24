"""SQLite Fieldbook store — editable community wiki pages with full revision history.

Every save writes a new `wiki_revisions` row and bumps `wiki_pages.revision`;
the page row carries the *current* body so reads never join. Revisions are
never rewritten — conflict detection (docs/protocol.md: "never silent
overwrite") is the service's job, using the monotonically increasing
`revision` this store maintains.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

FIELDBOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_pages (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_by TEXT NOT NULL COLLATE NOCASE,
    created_at REAL NOT NULL,
    updated_by TEXT NOT NULL COLLATE NOCASE,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wiki_pages_updated
    ON wiki_pages(updated_at DESC);

CREATE TABLE IF NOT EXISTS wiki_revisions (
    slug TEXT NOT NULL,
    revision INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL COLLATE NOCASE,
    summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY (slug, revision)
);
"""


class FieldbookStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(FIELDBOOK_SCHEMA)
        self._conn.commit()

    # -- pages -------------------------------------------------------------

    def create_page(
        self,
        *,
        slug: str,
        title: str,
        body: str,
        author: str,
        summary: str = "",
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO wiki_pages
                (slug, title, body, revision, created_by, created_at, updated_by, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (slug, title, body, author, ts, author, ts),
        )
        self._insert_revision(slug, 1, title, body, author, summary, ts)
        self._conn.commit()
        return self.get_page(slug)  # type: ignore[return-value]

    def save_revision(
        self,
        *,
        slug: str,
        title: str,
        body: str,
        author: str,
        summary: str = "",
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        """Append a revision and make it current. Caller has already checked
        the base revision — this only bumps whatever is stored now."""
        ts = created_at if created_at is not None else time.time()
        row = self._conn.execute(
            "SELECT revision FROM wiki_pages WHERE slug = ?", (slug,)
        ).fetchone()
        if not row:
            raise ValueError("page not found")
        next_rev = int(row["revision"]) + 1
        self._conn.execute(
            """
            UPDATE wiki_pages
               SET title = ?, body = ?, revision = ?, updated_by = ?, updated_at = ?
             WHERE slug = ?
            """,
            (title, body, next_rev, author, ts, slug),
        )
        self._insert_revision(slug, next_rev, title, body, author, summary, ts)
        self._conn.commit()
        return self.get_page(slug)  # type: ignore[return-value]

    def get_page(self, slug: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM wiki_pages WHERE slug = ?", (slug,)
        ).fetchone()
        return self._page_row(row) if row else None

    def list_pages(self, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            """
            SELECT slug, title, revision, updated_by, updated_at, length(body) AS size
              FROM wiki_pages
             ORDER BY lower(title)
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._header_row(r) for r in rows]

    def recent_pages(self, *, limit: int = 5) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        rows = self._conn.execute(
            """
            SELECT slug, title, revision, updated_by, updated_at, length(body) AS size
              FROM wiki_pages
             ORDER BY updated_at DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._header_row(r) for r in rows]

    def count_pages(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM wiki_pages").fetchone()
        return int(row["n"])

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Case-insensitive substring match on title or body. Title hits sort
        first. Returns headers plus the matching body offset so the service
        can cut a snippet without a second query."""
        limit = max(1, min(int(limit), 500))
        q = (query or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        rows = self._conn.execute(
            """
            SELECT slug, title, body, revision, updated_by, updated_at,
                   length(body) AS size,
                   instr(lower(title), lower(?)) AS title_hit,
                   instr(lower(body), lower(?)) AS body_hit
              FROM wiki_pages
             WHERE title LIKE ? OR body LIKE ?
             ORDER BY CASE WHEN instr(lower(title), lower(?)) > 0 THEN 0 ELSE 1 END,
                      updated_at DESC
             LIMIT ?
            """,
            (q, q, like, like, q, limit),
        ).fetchall()
        out = []
        for r in rows:
            header = self._header_row(r)
            header["body"] = r["body"]
            header["title_hit"] = int(r["title_hit"] or 0)
            header["body_hit"] = int(r["body_hit"] or 0)
            out.append(header)
        return out

    # -- revisions ---------------------------------------------------------

    def list_revisions(self, slug: str, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            """
            SELECT slug, revision, title, author, summary, created_at, length(body) AS size
              FROM wiki_revisions
             WHERE slug = ?
             ORDER BY revision DESC
             LIMIT ?
            """,
            (slug, limit),
        ).fetchall()
        return [
            {
                "slug": r["slug"],
                "revision": int(r["revision"]),
                "title": r["title"],
                "author": r["author"],
                "summary": r["summary"],
                "created_at": r["created_at"],
                "size": int(r["size"]),
            }
            for r in rows
        ]

    def get_revision(self, slug: str, revision: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM wiki_revisions WHERE slug = ? AND revision = ?",
            (slug, int(revision)),
        ).fetchone()
        if not row:
            return None
        return {
            "slug": row["slug"],
            "revision": int(row["revision"]),
            "title": row["title"],
            "body": row["body"],
            "author": row["author"],
            "summary": row["summary"],
            "created_at": row["created_at"],
            "size": len(row["body"]),
        }

    # -- helpers -----------------------------------------------------------

    def _insert_revision(
        self,
        slug: str,
        revision: int,
        title: str,
        body: str,
        author: str,
        summary: str,
        ts: float,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO wiki_revisions (slug, revision, title, body, author, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (slug, revision, title, body, author, summary or "", ts),
        )

    @staticmethod
    def _header_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "slug": row["slug"],
            "title": row["title"],
            "revision": int(row["revision"]),
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
            "size": int(row["size"]),
        }

    @staticmethod
    def _page_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "slug": row["slug"],
            "title": row["title"],
            "body": row["body"],
            "revision": int(row["revision"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
            "size": len(row["body"]),
        }
