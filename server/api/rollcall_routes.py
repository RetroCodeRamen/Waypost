"""Rollcall HTTP routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user


class PresenceTouch(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    via: str = "wifi"
    status: Optional[str] = Field(default=None, max_length=200)


class StatusUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    status: str = Field(max_length=200)


def build_rollcall_router() -> APIRouter:
    router = APIRouter(tags=["rollcall"])

    @router.get("/api/rollcall")
    def rollcall_list(request: Request, user=Depends(get_current_user)):
        _ = user
        return {"people": request.app.state.rollcall.list_people()}

    @router.get("/api/rollcall/{username}")
    def rollcall_get(
        username: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        person = request.app.state.rollcall.get(username)
        if not person:
            raise HTTPException(status_code=404, detail="Not found")
        return person

    @router.post("/api/rollcall/touch")
    def rollcall_touch(
        body: PresenceTouch, request: Request, user=Depends(get_current_user)
    ):
        username = actor_username(request, user, body.username)
        return request.app.state.rollcall.touch(
            username, via=body.via, status=body.status
        )

    @router.post("/api/rollcall/status")
    def rollcall_status(
        body: StatusUpdate, request: Request, user=Depends(get_current_user)
    ):
        username = actor_username(request, user, body.username)
        return request.app.state.rollcall.set_status(username, body.status)

    return router
