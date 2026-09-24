"""HTTP routes for Groups — HTTP/portal-only in v1, no Waylink ops."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.groups.constants import MAX_NAME, ROLE_MEMBER


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)


class GroupMemberAdd(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    role: str = Field(default=ROLE_MEMBER, max_length=16)


class GroupMemberRemove(BaseModel):
    username: str = Field(min_length=1, max_length=32)


def build_groups_router() -> APIRouter:
    router = APIRouter(tags=["groups"])

    @router.post("/api/groups", status_code=201)
    def create_group(body: GroupCreate, request: Request, user=Depends(get_current_user)):
        creator = actor_username(request, user)
        request.app.state.db.ensure_user(creator)
        try:
            return request.app.state.groups.create_group(name=body.name, created_by=creator)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/groups")
    def list_groups(request: Request, user=Depends(get_current_user)):
        username = actor_username(request, user)
        return {"groups": request.app.state.groups.list_groups_for_user(username)}

    @router.get("/api/groups/{group_id}")
    def get_group(group_id: str, request: Request, user=Depends(get_current_user)):
        viewer = actor_username(request, user)
        group = request.app.state.groups.get_group_for(group_id, viewer)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group

    @router.get("/api/groups/{group_id}/members")
    def list_members(group_id: str, request: Request, user=Depends(get_current_user)):
        viewer = actor_username(request, user)
        group = request.app.state.groups.get_group_for(group_id, viewer)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return {"members": group["members"]}

    @router.post("/api/groups/{group_id}/members")
    def add_member(
        group_id: str,
        body: GroupMemberAdd,
        request: Request,
        user=Depends(get_current_user),
    ):
        actor = actor_username(request, user)
        request.app.state.db.ensure_user(body.username)
        try:
            return request.app.state.groups.add_member(
                group_id, actor=actor, username=body.username, role=body.role
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            status = 404 if str(exc) == "group not found" else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.post("/api/groups/{group_id}/members/remove")
    def remove_member(
        group_id: str,
        body: GroupMemberRemove,
        request: Request,
        user=Depends(get_current_user),
    ):
        actor = actor_username(request, user)
        try:
            return request.app.state.groups.remove_member(
                group_id, actor=actor, username=body.username
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            status = 404 if str(exc) == "group not found" else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    return router
