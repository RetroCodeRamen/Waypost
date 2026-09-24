"""HTTP routes for Finder — cross-app search."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from server.api.deps import actor_username, get_current_user
from server.services.finder.constants import DEFAULT_LIMIT


def build_finder_router() -> APIRouter:
    router = APIRouter(tags=["finder"])

    @router.get("/api/finder/search")
    def search(
        request: Request,
        user=Depends(get_current_user),
        q: str = Query(default="", max_length=200),
        limit: int = DEFAULT_LIMIT,
        viewer: Optional[str] = None,
    ):
        username = actor_username(request, user, viewer)
        return {
            "q": q,
            "results": request.app.state.finder.search(q, username=username, limit=limit),
        }

    return router
