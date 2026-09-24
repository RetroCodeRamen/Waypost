"""HTTP routes for Fieldbook — the editable community wiki."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.fieldbook.constants import (
    MAX_BODY,
    MAX_SLUG,
    MAX_SUMMARY,
    MAX_TITLE,
    SEARCH_LIMIT_DEFAULT,
)
from server.services.fieldbook.service import RevisionConflict


class PageCreate(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    body: str = Field(default="", max_length=MAX_BODY)
    slug: Optional[str] = Field(default=None, max_length=MAX_SLUG)
    summary: str = Field(default="", max_length=MAX_SUMMARY)
    author: Optional[str] = None


class PageUpdate(BaseModel):
    base_revision: int
    body: Optional[str] = Field(default=None, max_length=MAX_BODY)
    title: Optional[str] = Field(default=None, max_length=MAX_TITLE)
    section: Optional[Any] = None
    section_text: Optional[str] = Field(default=None, max_length=MAX_BODY)
    summary: str = Field(default="", max_length=MAX_SUMMARY)
    author: Optional[str] = None


def build_fieldbook_router() -> APIRouter:
    router = APIRouter(tags=["fieldbook"])

    @router.get("/api/fieldbook/pages")
    def list_pages(request: Request, user=Depends(get_current_user), limit: int = 100):
        _ = user
        svc = request.app.state.fieldbook
        return {"pages": svc.list_pages(limit=limit), "count": svc.count_pages()}

    @router.get("/api/fieldbook/search")
    def search(
        request: Request,
        user=Depends(get_current_user),
        q: str = Query(default="", max_length=200),
        limit: int = SEARCH_LIMIT_DEFAULT,
    ):
        _ = user
        return {"q": q, "results": request.app.state.fieldbook.search(q, limit=limit)}

    @router.post("/api/fieldbook/pages", status_code=201)
    def create_page(body: PageCreate, request: Request, user=Depends(get_current_user)):
        author = actor_username(request, user, body.author)
        request.app.state.db.ensure_user(author)
        try:
            return request.app.state.fieldbook.create_page(
                author=author,
                title=body.title,
                body=body.body,
                slug=body.slug,
                summary=body.summary,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/fieldbook/pages/{slug}")
    def get_page(
        slug: str,
        request: Request,
        user=Depends(get_current_user),
        section: Optional[str] = None,
        since: Optional[int] = None,
        outline: bool = False,
    ):
        _ = user
        svc = request.app.state.fieldbook
        page = svc.get_page(slug)
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        if since is not None:
            if since == page["revision"]:
                return {"slug": slug, "revision": page["revision"], "unchanged": True}
            d = svc.diff(slug, since)
            if d is not None:
                return d
        if section is not None:
            found = svc.get_section(slug, section)
            if not found:
                raise HTTPException(status_code=404, detail="Section not found")
            return found
        if outline:
            return svc.get_outline(slug)
        page = dict(page)
        page["outline"] = svc.get_outline(slug)["outline"]
        return page

    @router.put("/api/fieldbook/pages/{slug}")
    def update_page(
        slug: str, body: PageUpdate, request: Request, user=Depends(get_current_user)
    ):
        author = actor_username(request, user, body.author)
        request.app.state.db.ensure_user(author)
        try:
            return request.app.state.fieldbook.update_page(
                slug,
                author=author,
                base_revision=body.base_revision,
                body=body.body,
                title=body.title,
                section=body.section,
                section_text=body.section_text,
                summary=body.summary,
            )
        except RevisionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={"error": "revision_conflict", "current": conflict.current},
            ) from conflict
        except ValueError as exc:
            status = 404 if str(exc) in ("page not found", "section not found") else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.get("/api/fieldbook/pages/{slug}/history")
    def history(slug: str, request: Request, user=Depends(get_current_user), limit: int = 50):
        _ = user
        revs = request.app.state.fieldbook.history(slug, limit=limit)
        if revs is None:
            raise HTTPException(status_code=404, detail="Page not found")
        return {"slug": slug, "revisions": revs}

    @router.get("/api/fieldbook/pages/{slug}/revisions/{revision}")
    def get_revision(
        slug: str, revision: int, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        rev = request.app.state.fieldbook.get_revision(slug, revision)
        if not rev:
            raise HTTPException(status_code=404, detail="Revision not found")
        return rev

    @router.get("/api/fieldbook/pages/{slug}/diff")
    def diff(
        slug: str,
        request: Request,
        user=Depends(get_current_user),
        from_revision: int = Query(alias="from"),
        to_revision: Optional[int] = Query(default=None, alias="to"),
    ):
        _ = user
        d = request.app.state.fieldbook.diff(slug, from_revision, to_revision)
        if d is None:
            raise HTTPException(status_code=404, detail="Page or revision not found")
        return d

    return router
