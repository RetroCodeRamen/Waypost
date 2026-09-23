"""Auth HTTP routes — register / login / logout / me."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from server.api.deps import get_current_user, get_optional_user


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=80)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


def build_auth_router() -> APIRouter:
    router = APIRouter(tags=["auth"])

    def _set_cookie(request: Request, response: Response, token: str) -> None:
        # Behind Caddy, uvicorn --proxy-headers makes the scheme reflect the client's HTTPS
        response.set_cookie(
            key="waypost_session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 24 * 14,
            path="/",
        )

    @router.post("/api/auth/register")
    def register(body: RegisterBody, request: Request, response: Response):
        settings = request.app.state.settings
        if settings.waypost_registration_mode == "INVITE_ONLY":
            raise HTTPException(status_code=403, detail="registration invite-only")
        try:
            result = request.app.state.auth.register(
                username=body.username,
                password=body.password,
                display_name=body.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _set_cookie(request, response, result["token"])
        return result

    @router.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        try:
            result = request.app.state.auth.login(
                username=body.username, password=body.password
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        _set_cookie(request, response, result["token"])
        return result

    @router.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(get_optional_user)):
        token = getattr(request.state, "token", None)
        if not token:
            # try cookie
            token = request.cookies.get("waypost_session")
        if token:
            request.app.state.auth.logout(token)
        response.delete_cookie("waypost_session", path="/")
        return {"ok": True}

    @router.get("/api/auth/me")
    def me(user=Depends(get_current_user)):
        return {"user": user}

    return router
