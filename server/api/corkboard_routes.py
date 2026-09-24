"""HTTP routes for Corkboard — per-outpost public note board.

Reading/posting is always scoped to one outpost_id in the URL; there is no
"all outposts" endpoint, by design (see docs/architecture.md).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import get_current_user
from server.services.corkboard.constants import MAX_BODY, MAX_SIGNATURE


class NotePost(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)
    signature: Optional[str] = Field(default=None, max_length=MAX_SIGNATURE)


def build_corkboard_router() -> APIRouter:
    router = APIRouter(tags=["corkboard"])

    @router.get("/api/corkboard/outposts")
    def list_outposts(request: Request, user=Depends(get_current_user)):
        _ = user
        return {"outposts": request.app.state.corkboard.list_outposts()}

    @router.get("/api/corkboard/outposts/{outpost_id}/notes")
    def list_notes(
        outpost_id: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        return {"notes": request.app.state.corkboard.list_notes(outpost_id)}

    @router.post("/api/corkboard/outposts/{outpost_id}/notes", status_code=201)
    def post_note(
        outpost_id: str,
        body: NotePost,
        request: Request,
        user=Depends(get_current_user),
    ):
        _ = user
        try:
            note = request.app.state.corkboard.post_note(
                outpost_id=outpost_id, body=body.body, signature=body.signature
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return note

    return router
