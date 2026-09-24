"""Station account auth — register / login / sessions."""

from __future__ import annotations

import secrets
import time
from typing import Any, Optional

from server.api.db import Database
from server.services.auth.passwords import hash_password, verify_password


class AuthService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def register(
        self,
        *,
        username: str,
        password: str,
        display_name: Optional[str] = None,
        registration_mode: str = "OPEN",
    ) -> dict[str, Any]:
        username = username.strip()
        if not username or len(username) > 32:
            raise ValueError("invalid username")
        if self.db.get_user_by_username(username):
            raise ValueError("username taken")
        pw_hash = hash_password(password)
        now = time.time()
        # First account ever on this Station bootstraps as admin, and is
        # auto-approved regardless of mode — otherwise an ADMIN_APPROVAL
        # Station could never have anyone able to approve anyone.
        is_first_user = self.db.count_users() == 0
        if is_first_user:
            is_admin = True
            approved_at: Optional[float] = now
        else:
            is_admin = False
            approved_at = None if registration_mode == "ADMIN_APPROVAL" else now
        user = self.db.create_user(
            username,
            (display_name or username).strip() or username,
            password_hash=pw_hash,
            is_admin=is_admin,
            approved_at=approved_at,
        )
        if approved_at is None:
            return {"user": self._public_user(user), "pending_approval": True}
        session = self.create_session(user["username"])
        return {"user": self._public_user(user), "token": session["token"]}

    def login(self, *, username: str, password: str) -> dict[str, Any]:
        user = self.db.get_user_by_username(username.strip())
        if not user or not user.get("password_hash"):
            raise ValueError("invalid credentials")
        if not verify_password(password, user["password_hash"]):
            raise ValueError("invalid credentials")
        if not user.get("is_admin") and not user.get("approved_at"):
            raise ValueError("account pending admin approval")
        session = self.create_session(user["username"])
        return {"user": self._public_user(user), "token": session["token"]}

    def list_pending_users(self) -> list[dict[str, Any]]:
        return self.db.list_pending_users()

    def approve_user(self, username: str) -> dict[str, Any]:
        user = self.db.get_user_by_username(username.strip())
        if not user:
            raise ValueError("user not found")
        if user.get("approved_at"):
            raise ValueError("user already approved")
        approved = self.db.approve_user(username.strip(), approved_at=time.time())
        return self._public_user(approved)  # type: ignore[arg-type]

    def create_session(self, username: str, *, ttl_seconds: int = 60 * 60 * 24 * 14) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + ttl_seconds
        self.db.create_session(token=token, username=username, created_at=now, expires_at=expires)
        return {"token": token, "username": username, "expires_at": expires}

    def user_for_token(self, token: str) -> Optional[dict[str, Any]]:
        if not token:
            return None
        row = self.db.get_session(token)
        if not row:
            return None
        if float(row["expires_at"]) < time.time():
            self.db.delete_session(token)
            return None
        user = self.db.get_user_by_username(row["username"])
        if not user:
            return None
        return self._public_user(user)

    def logout(self, token: str) -> None:
        self.db.delete_session(token)

    @staticmethod
    def _public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "status": user.get("status") or "",
            "bio": user.get("bio") or "",
            "is_admin": bool(user.get("is_admin")),
            "approved": bool(user.get("approved_at")),
        }
