"""HTTP routes for Beacon."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.beacon.constants import MAX_BODY, MAX_TITLE


class BeaconPush(BaseModel):
    author: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    body: str = Field(min_length=1, max_length=MAX_BODY)
    severity: str = Field(default="emergency", max_length=32)
    id: Optional[str] = None
    mid: Optional[str] = None
    bypass_cooldown: bool = False


class BeaconClear(BaseModel):
    id: Optional[str] = None


def build_beacon_router() -> APIRouter:
    router = APIRouter(tags=["beacon"])

    @router.get("/api/beacon")
    def get_active(request: Request, user=Depends(get_current_user)):
        _ = user
        return {"beacon": request.app.state.beacon.get_active()}

    @router.get("/api/beacon/history")
    def list_history(
        request: Request,
        user=Depends(get_current_user),
        limit: int = 20,
        active_only: bool = False,
    ):
        _ = user
        return {
            "beacons": request.app.state.beacon.list_beacons(
                limit=limit, active_only=active_only
            )
        }

    @router.get("/api/beacon/{beacon_id}")
    def get_beacon(
        beacon_id: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        beacon = request.app.state.beacon.get(beacon_id)
        if not beacon:
            raise HTTPException(status_code=404, detail="Beacon not found")
        return beacon

    @router.post("/api/beacon", status_code=201)
    def push_beacon(
        body: BeaconPush, request: Request, user=Depends(get_current_user)
    ):
        author = actor_username(request, user, body.author)
        request.app.state.db.ensure_user(author)
        bypass = body.bypass_cooldown or (
            getattr(request.app.state.settings, "waypost_env", "")
            in ("test", "development")
        )
        try:
            beacon = request.app.state.beacon.push(
                author=author,
                title=body.title,
                body=body.body,
                severity=body.severity,
                beacon_id=body.id,
                mid=body.mid,
                bypass_cooldown=bypass,
            )
        except ValueError as exc:
            status = 429 if "rate limited" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return beacon

    @router.post("/api/beacon/clear")
    def clear_beacon(
        body: BeaconClear, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        cleared = request.app.state.beacon.clear(body.id)
        return {"beacon": cleared}

    return router
