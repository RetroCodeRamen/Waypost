"""Rollcall — people / presence directory."""

from __future__ import annotations

import time
from typing import Any, Optional


class RollcallService:
    def __init__(self, db) -> None:
        self._db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._db._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS presence (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                status TEXT NOT NULL DEFAULT '',
                last_seen REAL,
                via TEXT
            );
            """
        )
        self._db._conn.commit()

    def touch(self, username: str, *, via: str = "wifi", status: Optional[str] = None) -> dict[str, Any]:
        self._db.ensure_user(username)
        now = time.time()
        row = self._db._conn.execute(
            "SELECT status FROM presence WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        current_status = status if status is not None else (row["status"] if row else "")
        self._db._conn.execute(
            """
            INSERT INTO presence (username, status, last_seen, via)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                status = excluded.status,
                last_seen = excluded.last_seen,
                via = excluded.via
            """,
            (username, current_status or "", now, via),
        )
        # Also update users.status when provided
        if status is not None:
            self._db._conn.execute(
                "UPDATE users SET status = ? WHERE username = ? COLLATE NOCASE",
                (status, username),
            )
        self._db._conn.commit()
        return self.get(username)  # type: ignore[return-value]

    def set_status(self, username: str, status: str) -> dict[str, Any]:
        return self.touch(username, via="wifi", status=status)

    def get(self, username: str) -> Optional[dict[str, Any]]:
        user = self._db.get_user_by_username(username)
        if not user:
            return None
        presence = self._db._conn.execute(
            "SELECT status, last_seen, via FROM presence WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        nodes = self._db.dispatch.nodes_for_user(username)
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
        users = self._db.list_users()
        return [self.get(u["username"]) for u in users if self.get(u["username"])]
