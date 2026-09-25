"""Rollcall — people / presence directory."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from server.services.profiles.store import RollcallStore


class RollcallService:
    def __init__(
        self,
        store: RollcallStore,
        *,
        get_user: Callable[[str], Optional[dict[str, Any]]],
        ensure_user: Callable[[str], dict[str, Any]],
        set_user_status: Callable[[str, str], None],
        list_users: Callable[[], list[dict[str, Any]]],
        nodes_for_user: Callable[[str], list[str]],
    ) -> None:
        self.store = store
        # Injected the same way NoticeboardService/BeaconService take
        # get_binding -- Rollcall previously took the raw Database and
        # reached into users (owned by Database) and dispatch (owned by
        # DispatchStore) directly instead of through their own accessors.
        self._get_user = get_user
        self._ensure_user = ensure_user
        self._set_user_status = set_user_status
        self._list_users = list_users
        self._nodes_for_user = nodes_for_user

    def touch(
        self, username: str, *, via: str = "wifi", status: Optional[str] = None
    ) -> dict[str, Any]:
        self._ensure_user(username)
        now = time.time()
        presence = self.store.get_presence(username)
        current_status = status if status is not None else (presence["status"] if presence else "")
        self.store.upsert_presence(
            username, status=current_status or "", last_seen=now, via=via
        )
        if status is not None:
            self._set_user_status(username, status)
        return self.get(username)  # type: ignore[return-value]

    def set_status(self, username: str, status: str) -> dict[str, Any]:
        return self.touch(username, via="wifi", status=status)

    def get(self, username: str) -> Optional[dict[str, Any]]:
        user = self._get_user(username)
        if not user:
            return None
        presence = self.store.get_presence(username)
        nodes = self._nodes_for_user(username)
        now = time.time()
        last_seen = presence["last_seen"] if presence else None
        via = presence["via"] if presence else None
        status = (presence["status"] if presence else None) or user.get("status") or ""

        reachability = []
        if via == "wifi" and last_seen and (now - last_seen) < 300:
            reachability.append("wifi")
        if nodes:
            reachability.append("lora")
        if not reachability:
            if last_seen and (now - last_seen) < 3600:
                label = "recent"
            else:
                label = "unavailable"
        else:
            label = "+".join(reachability)

        return {
            "username": user["username"],
            "display_name": user["display_name"],
            "status": status,
            "bio": user.get("bio") or "",
            "last_seen": last_seen,
            "via": via,
            "nodes": nodes,
            "reachability": label,
            "email": f"{user['username'].lower()}@waypost",
            "profile": f"/~{user['username']}",
        }

    def list_people(self) -> list[dict[str, Any]]:
        users = self._list_users()
        return [self.get(u["username"]) for u in users if self.get(u["username"])]
