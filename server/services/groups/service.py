"""Groups service — validation layer over GroupsStore.

v1 enforces exactly two ranks (member/admin) per docs/groups-and-permissions.md's
explicit deferral of full custom roles to v2. Other services (Locker, Dispatch)
call require_member/is_member through an injected lookup rather than importing
GroupsStore directly — same pattern as PostboxService.set_nodes_lookup.
"""

from __future__ import annotations

from typing import Any, Optional

from server.services.groups.constants import ALLOWED_ROLES, MAX_NAME, ROLE_ADMIN, ROLE_MEMBER
from server.services.groups.store import GroupsStore


class GroupsService:
    def __init__(self, store: GroupsStore) -> None:
        self.store = store

    def create_group(self, *, name: str, created_by: str) -> dict[str, Any]:
        name = (name or "").strip()
        created_by = (created_by or "").strip()
        if not name:
            raise ValueError("name required")
        if len(name) > MAX_NAME:
            raise ValueError(f"name too long (max {MAX_NAME})")
        if not created_by:
            raise ValueError("created_by required")
        return self.store.create_group(name=name, created_by=created_by)

    def get_group(self, group_id: str) -> Optional[dict[str, Any]]:
        return self.store.get_group(group_id)

    def list_groups_for_user(self, username: str) -> list[dict[str, Any]]:
        return self.store.list_groups_for_user(username)

    def list_members(self, group_id: str) -> list[dict[str, Any]]:
        return self.store.list_members(group_id)

    def is_member(self, group_id: str, username: str) -> bool:
        return self.store.is_member(group_id, username)

    def require_admin(self, group_id: str, username: str) -> None:
        if not self.store.get_group(group_id):
            raise ValueError("group not found")
        if not self.store.is_admin(group_id, username):
            raise PermissionError("only a group admin can do that")

    def add_member(
        self, group_id: str, *, actor: str, username: str, role: str = ROLE_MEMBER
    ) -> dict[str, Any]:
        role = (role or ROLE_MEMBER).strip().lower()
        username = (username or "").strip()
        if not username:
            raise ValueError("username required")
        if role not in ALLOWED_ROLES:
            raise ValueError("role must be member or admin")
        self.require_admin(group_id, actor)
        self.store.add_member(group_id, username, role=role)
        return self.store.get_group(group_id)  # type: ignore[return-value]

    def remove_member(self, group_id: str, *, actor: str, username: str) -> dict[str, Any]:
        username = (username or "").strip()
        if not username:
            raise ValueError("username required")
        self.require_admin(group_id, actor)
        if (
            self.store.get_role(group_id, username) == ROLE_ADMIN
            and self.store.count_admins(group_id) <= 1
        ):
            raise ValueError("cannot remove the last admin")
        self.store.remove_member(group_id, username)
        return self.store.get_group(group_id)  # type: ignore[return-value]
