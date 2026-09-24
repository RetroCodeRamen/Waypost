"""SQLite + filesystem Locker store."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from server.services.locker.constants import SCOPE_GROUP, SCOPE_PERSONAL, SCOPE_SHARED
from shared.protocol.envelope import new_id


LOCKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS locker_files (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL COLLATE NOCASE,
    scope TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    stored_name TEXT NOT NULL,
    created_at REAL NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_locker_scope_created
    ON locker_files(scope, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_locker_owner
    ON locker_files(owner, created_at DESC);
"""


class LockerStore:
    def __init__(self, conn: sqlite3.Connection, root: Path) -> None:
        self._conn = conn
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._conn.executescript(LOCKER_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(locker_files)").fetchall()
        }
        if "group_id" not in cols:
            self._conn.execute("ALTER TABLE locker_files ADD COLUMN group_id TEXT")

    def path_for(self, stored_name: str) -> Path:
        return self.root / stored_name

    def create(
        self,
        *,
        owner: str,
        scope: str,
        filename: str,
        content_type: str,
        size: int,
        stored_name: str,
        note: str = "",
        file_id: Optional[str] = None,
        created_at: Optional[float] = None,
        group_id: Optional[str] = None,
    ) -> dict[str, Any]:
        fid = file_id or new_id()
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO locker_files
                (id, owner, scope, filename, content_type, size, note, stored_name, created_at, deleted, group_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                fid,
                owner,
                scope,
                filename,
                content_type or "application/octet-stream",
                int(size),
                note or "",
                stored_name,
                ts,
                group_id,
            ),
        )
        self._conn.commit()
        return self.get(fid)  # type: ignore[return-value]

    def get(self, file_id: str, *, include_deleted: bool = False) -> Optional[dict[str, Any]]:
        if include_deleted:
            row = self._conn.execute(
                "SELECT * FROM locker_files WHERE id = ?", (file_id,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM locker_files WHERE id = ? AND deleted = 0",
                (file_id,),
            ).fetchone()
        return self._row(row) if row else None

    def list_files(
        self,
        *,
        scope: Optional[str] = None,
        owner: Optional[str] = None,
        viewer: Optional[str] = None,
        limit: int = 100,
        is_group_member: Optional[Any] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List visible files.

        - shared: visible to everyone
        - personal: visible only to owner (viewer must match)
        - group: visible only to members of item["group_id"] (via is_group_member)
        """
        limit = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            """
            SELECT * FROM locker_files
            WHERE deleted = 0
            ORDER BY created_at DESC
            LIMIT 500
            """
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = self._row(row)
            if scope and item["scope"] != scope:
                continue
            if owner and item["owner"].lower() != owner.lower():
                continue
            if group_id and item.get("group_id") != group_id:
                continue
            if item["scope"] == SCOPE_PERSONAL:
                if not viewer or viewer.lower() != item["owner"].lower():
                    continue
            elif item["scope"] == SCOPE_GROUP:
                gid = item.get("group_id")
                if not viewer or not gid or not is_group_member or not is_group_member(gid, viewer):
                    continue
            elif item["scope"] != SCOPE_SHARED:
                continue
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def soft_delete(self, file_id: str) -> Optional[dict[str, Any]]:
        self._conn.execute(
            "UPDATE locker_files SET deleted = 1 WHERE id = ? AND deleted = 0",
            (file_id,),
        )
        self._conn.commit()
        return self.get(file_id, include_deleted=True)

    def count_shared(self) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM locker_files
            WHERE deleted = 0 AND scope = ?
            """,
            (SCOPE_SHARED,),
        ).fetchone()
        return int(row["n"])

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "owner": row["owner"],
            "scope": row["scope"],
            "filename": row["filename"],
            "content_type": row["content_type"],
            "size": int(row["size"]),
            "note": row["note"] or "",
            "stored_name": row["stored_name"],
            "created_at": row["created_at"],
            "deleted": bool(row["deleted"]),
            "group_id": row["group_id"] if "group_id" in row.keys() else None,
        }
