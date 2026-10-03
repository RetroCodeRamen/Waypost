"""HTTP routes for Trailhead — the Station's small web of linked text pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.trailhead.constants import MAX_BODY, MAX_TITLE


class PagePut(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    body: str = Field(default="", max_length=MAX_BODY)
    author: str | None = None


def build_trailhead_router() -> APIRouter:
    router = APIRouter(tags=["trailhead"])

    @router.get("/api/trailhead/pages")
    def list_pages(request: Request, user=Depends(get_current_user)):
        _ = user
        return {"pages": request.app.state.trailhead.list_pages()}

    @router.get("/api/trailhead/pages/{path:path}")
    def get_page(path: str, request: Request, user=Depends(get_current_user)):
        _ = user
        page = request.app.state.trailhead.get_page(path)
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        return page

    @router.put("/api/trailhead/pages/{path:path}")
    def put_page(path: str, body: PagePut, request: Request, user=Depends(get_current_user)):
        author = actor_username(request, user, body.author)
        try:
            return request.app.state.trailhead.save_page(
                path, title=body.title, body=body.body, author=author
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/trailhead/pages/{path:path}")
    def delete_page(path: str, request: Request, user=Depends(get_current_user)):
        _ = user
        if not request.app.state.trailhead.delete_page(path):
            raise HTTPException(status_code=404, detail="Page not found")
        return {"deleted": path}

    return router
