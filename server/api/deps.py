"""Auth FastAPI dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request


def _extract_token(
    authorization: Optional[str],
    waypost_session: Optional[str],
) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if waypost_session:
        return waypost_session.strip()
    return None


def auth_enforced(request: Request) -> bool:
    """True when HTTP APIs must reject anonymous callers."""
    settings = request.app.state.settings
    return bool(settings.waypost_auth_required and settings.waypost_env != "test")


def actor_username(request: Request, user: dict, claimed: Optional[str] = None) -> str:
    """Prefer session identity when auth is on; else honor claimed name (tests)."""
    if auth_enforced(request):
        return user["username"]
    return (claimed or user.get("username") or "aj").strip()


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    waypost_session: Optional[str] = Cookie(default=None, alias="waypost_session"),
) -> dict:
    settings = request.app.state.settings
    auth = request.app.state.auth
    token = _extract_token(authorization, waypost_session)
    if token:
        user = auth.user_for_token(token)
        if user:
            request.state.user = user
            request.state.token = token
            return user

    # Automated tests / explicit lab override: allow anonymous as seeded "aj"
    if settings.waypost_env == "test" or not settings.waypost_auth_required:
        user = request.app.state.db.ensure_user("aj", "AJ")
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "status": user.get("status") or "",
            "bio": user.get("bio") or "",
            # Permissive test/lab mode — same spirit as bypassing auth
            # entirely here; don't make admin-gated routes untestable.
            "is_admin": True,
            "approved": True,
        }

    raise HTTPException(status_code=401, detail="authentication required")


def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
    return user


def get_optional_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    waypost_session: Optional[str] = Cookie(default=None, alias="waypost_session"),
) -> Optional[dict]:
    token = _extract_token(authorization, waypost_session)
    if not token:
        return None
    return request.app.state.auth.user_for_token(token)
