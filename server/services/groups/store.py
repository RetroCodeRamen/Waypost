"""SQLite Groups store — the one authorization model other services consult.

docs/groups-and-permissions.md is explicit: "do not implement a second ACL
per app." This store is that single model; Locker/Dispatch integrate by
calling is_member()/get_role() through an injected lookup, the same
cross-service pattern as NoticeboardService's get_binding.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from server.services.groups.constants import ROLE_ADMIN, ROLE_MEMBER
from shared.protocol.envelope import new_id


GROUPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_by TEXT NOT NULL COLLATE NOCASE,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    role TEXT NOT NULL DEFAULT 'member',
    added_at REAL NOT NULL,
    PRIMARY KEY (group_id, username),
    FOREIGN KEY (group_id) REFERENCES groups(id)
);

CREATE INDEX IF NOT EXISTS idx_group_members_user
    ON group_members(username);
"""


class GroupsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(GROUPS_SCHEMA)
        self._conn.commit()

    def create_group(
        self,
        *,
        name: str,
        created_by: str,
        group_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        gid = group_id or new_id()
        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            "INSERT INTO groups (id, name, created_by, created_at) VALUES (?, ?, ?, ?)",
            (gid, name, created_by, ts),
        )
        self._conn.execute(
            """
            INSERT INTO group_members (group_id, username, role, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (gid, created_by, ROLE_ADMIN, ts),
        )
        self._conn.commit()
        return self.get_group(gid)  # type: ignore[return-value]

    def get_group(self, group_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM groups WHERE id = ?", (group_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["members"] = self.list_members(group_id)
        return data

    def list_groups_for_user(self, username: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT g.* FROM groups g
            JOIN group_members m ON m.group_id = g.id
            WHERE m.username = ? COLLATE NOCASE
            ORDER BY g.created_at DESC
            """,
            (username,),
        ).fetchall()
        return [self.get_group(r["id"]) for r in rows]  # type: ignore[misc]

    def list_members(self, group_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT username, role, added_at FROM group_members
            WHERE group_id = ?
            ORDER BY added_at ASC
            """,
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_member(self, group_id: str, username: str, *, role: str = ROLE_MEMBER) -> None:
        self._conn.execute(
            """
            INSERT INTO group_members (group_id, username, role, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(group_id, username) DO UPDATE SET role = excluded.role
            """,
            (group_id, username, role, time.time()),
        )
        self._conn.commit()

    def remove_member(self, group_id: str, username: str) -> None:
        self._conn.execute(
            "DELETE FROM group_members WHERE group_id = ? AND username = ? COLLATE NOCASE",
            (group_id, username),
        )
        self._conn.commit()

    def get_role(self, group_id: str, username: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT role FROM group_members WHERE group_id = ? AND username = ? COLLATE NOCASE",
            (group_id, username),
        ).fetchone()
        return row["role"] if row else None

    def is_member(self, group_id: str, username: str) -> bool:
        return self.get_role(group_id, username) is not None

    def is_admin(self, group_id: str, username: str) -> bool:
        return self.get_role(group_id, username) == ROLE_ADMIN

    def count_admins(self, group_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM group_members WHERE group_id = ? AND role = ?",
            (group_id, ROLE_ADMIN),
        ).fetchone()
        return int(row["n"])
