"""HTTP routes for Locker — authenticated users upload/download shared files."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.locker.constants import MAX_UPLOAD_BYTES, SCOPE_SHARED


class LockerDelete(BaseModel):
    actor: str = Field(min_length=1, max_length=32)


def build_locker_router() -> APIRouter:
    router = APIRouter(tags=["locker"])

    @router.get("/api/locker/files")
    def list_files(
        request: Request,
        user=Depends(get_current_user),
        scope: Optional[str] = None,
        owner: Optional[str] = None,
        viewer: Optional[str] = None,
        limit: int = 100,
    ):
        viewer_name = actor_username(request, user, viewer)
        return {
            "files": request.app.state.locker.list_files(
                scope=scope, owner=owner, viewer=viewer_name, limit=limit
            ),
            "shared_count": request.app.state.locker.count_shared(),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
        }

    @router.get("/api/locker/files/{file_id}")
    def file_info(
        file_id: str,
        request: Request,
        user=Depends(get_current_user),
        viewer: Optional[str] = None,
    ):
        viewer_name = actor_username(request, user, viewer)
        info = request.app.state.locker.info(file_id, viewer=viewer_name)
        if not info:
            raise HTTPException(status_code=404, detail="File not found")
        return info

    @router.get("/api/locker/files/{file_id}/download")
    def download_file(
        file_id: str,
        request: Request,
        user=Depends(get_current_user),
        viewer: Optional[str] = None,
    ):
        viewer_name = actor_username(request, user, viewer)
        info = request.app.state.locker.info(file_id, viewer=viewer_name)
        path = request.app.state.locker.disk_path(file_id, viewer=viewer_name)
        if not info or not path:
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(
            path,
            filename=info["filename"],
            media_type=info.get("content_type") or "application/octet-stream",
        )

    @router.post("/api/locker/files", status_code=201)
    async def upload_file(
        request: Request,
        user=Depends(get_current_user),
        file: UploadFile = File(...),
        owner: str = Form("aj"),
        scope: str = Form(SCOPE_SHARED),
        note: str = Form(""),
    ):
        owner_name = actor_username(request, user, owner)
        request.app.state.db.ensure_user(owner_name)
        raw = await file.read()
        try:
            item = request.app.state.locker.upload(
                owner=owner_name,
                filename=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
                data=raw,
                scope=scope,
                note=note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return item

    @router.post("/api/locker/files/{file_id}/delete")
    def delete_file(
        file_id: str,
        body: LockerDelete,
        request: Request,
        user=Depends(get_current_user),
    ):
        actor = actor_username(request, user, body.actor)
        try:
            deleted = request.app.state.locker.delete(file_id, actor=actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="File not found")
        return deleted

    return router
