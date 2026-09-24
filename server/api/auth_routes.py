"""Auth HTTP routes — register / login / logout / me."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from server.api.deps import get_current_admin, get_current_user, get_optional_user
from server.services.auth.pairing import CODE_LENGTH


class ApproveUserBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=80)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class PairingRedeem(BaseModel):
    code: str = Field(min_length=CODE_LENGTH, max_length=CODE_LENGTH, pattern=r"^[0-9]+$")
    node_id: str = Field(min_length=1, max_length=64)
    transport_dest: Optional[str] = Field(default=None, max_length=128)


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
                registration_mode=settings.waypost_registration_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # ADMIN_APPROVAL: account created but not yet usable — no session
        # to hand out until an admin approves it.
        if result.get("pending_approval"):
            return result
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

    @router.get("/api/auth/registration_mode")
    def registration_mode(request: Request):
        return {"mode": request.app.state.settings.waypost_registration_mode}

    @router.get("/api/auth/pending")
    def pending_users(request: Request, admin=Depends(get_current_admin)):
        _ = admin
        return {"users": request.app.state.auth.list_pending_users()}

    @router.post("/api/auth/approve")
    def approve_user(body: ApproveUserBody, request: Request, admin=Depends(get_current_admin)):
        _ = admin
        try:
            return request.app.state.auth.approve_user(body.username)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/auth/pairing/create")
    def create_pairing_code(request: Request, user=Depends(get_current_user)):
        """Short-lived single-use code a device can redeem to bind itself
        to this account — no password ever needs to cross LoRa."""
        return request.app.state.pairing.create_code(user["username"])

    @router.post("/api/auth/pairing/redeem")
    def redeem_pairing_code(body: PairingRedeem, request: Request):
        """Deliberately unauthenticated: this is how a device with no
        session yet (radio-only, or first Wi-Fi contact) binds itself. The
        code is the credential — short TTL, single use."""
        try:
            return request.app.state.pairing.redeem_code(
                code=body.code,
                node_id=body.node_id,
                transport_dest=body.transport_dest,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
