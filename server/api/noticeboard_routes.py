"""HTTP routes for Noticeboard."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.noticeboard.constants import MAX_BODY, MAX_TITLE


class NoticeCreate(BaseModel):
    author: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    body: str = Field(min_length=1, max_length=MAX_BODY)
    priority: str = Field(default="normal", max_length=16)
    expires_at: Optional[float] = None
    id: Optional[str] = None


def build_noticeboard_router() -> APIRouter:
    router = APIRouter(tags=["noticeboard"])

    @router.get("/api/noticeboard/notices")
    def list_notices(
        request: Request,
        user=Depends(get_current_user),
        active_only: bool = True,
        limit: int = 50,
    ):
        _ = user
        return {
            "notices": request.app.state.noticeboard.list_notices(
                active_only=active_only, limit=limit
            ),
            "active_count": request.app.state.noticeboard.count_active(),
        }

    @router.get("/api/noticeboard/notices/{notice_id}")
    def get_notice(
        notice_id: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        notice = request.app.state.noticeboard.get(notice_id)
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        return notice

    @router.post("/api/noticeboard/notices", status_code=201)
    def create_notice(
        body: NoticeCreate, request: Request, user=Depends(get_current_user)
    ):
        author = actor_username(request, user, body.author)
        request.app.state.db.ensure_user(author)
        try:
            notice = request.app.state.noticeboard.create(
                author=author,
                title=body.title,
                body=body.body,
                priority=body.priority,
                expires_at=body.expires_at,
                notice_id=body.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return notice

    @router.post("/api/noticeboard/notices/{notice_id}/expire")
    def expire_notice(
        notice_id: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        notice = request.app.state.noticeboard.expire(notice_id)
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        return notice

    return router
