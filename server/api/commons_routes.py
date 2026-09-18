"""HTTP routes for Commons."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.commons.constants import MAX_BODY, MAX_TITLE


class PostCreate(BaseModel):
    author: str = Field(min_length=1, max_length=32)
    body: str = Field(min_length=1, max_length=MAX_BODY)
    title: str = Field(default="", max_length=MAX_TITLE)
    id: Optional[str] = None


def build_commons_router() -> APIRouter:
    router = APIRouter(tags=["commons"])

    @router.get("/api/commons/posts")
    def list_posts(
        request: Request,
        user=Depends(get_current_user),
        limit: int = 50,
        since: Optional[float] = None,
    ):
        _ = user
        return {
            "posts": request.app.state.commons.list_posts(limit=limit, since=since),
        }

    @router.get("/api/commons/posts/{post_id}")
    def get_post(post_id: str, request: Request, user=Depends(get_current_user)):
        _ = user
        post = request.app.state.commons.get(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        return post

    @router.post("/api/commons/posts", status_code=201)
    def create_post(
        body: PostCreate, request: Request, user=Depends(get_current_user)
    ):
        author = actor_username(request, user, body.author)
        request.app.state.db.ensure_user(author)
        try:
            post = request.app.state.commons.create(
                author=author,
                body=body.body,
                title=body.title,
                post_id=body.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return post

    return router
