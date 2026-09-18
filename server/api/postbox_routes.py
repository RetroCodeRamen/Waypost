"""HTTP routes for Postbox."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import actor_username, get_current_user
from server.services.mail.constants import FOLDER_INBOX
from server.services.mail.store import addr_for_user


class MailSend(BaseModel):
    from_user: str = Field(min_length=1, max_length=32)
    to: str = Field(min_length=1, max_length=120)
    subject: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=20000)
    message_id: Optional[str] = None
    attachment_name: Optional[str] = None
    attachment_size: Optional[int] = None
    queue_only: bool = False


class MailReply(BaseModel):
    from_user: str = Field(min_length=1, max_length=32)
    local_id: int
    body: str = Field(min_length=1, max_length=20000)
    folder: str = FOLDER_INBOX
    queue_only: bool = False


class MailMark(BaseModel):
    mailbox: str = Field(min_length=1, max_length=32)
    local_id: Optional[int] = None
    message_id: Optional[str] = None
    folder: str = FOLDER_INBOX
    read: Optional[bool] = None
    delete: bool = False


class MailFlush(BaseModel):
    mailbox: str = Field(min_length=1, max_length=32)
    local_id: Optional[int] = None
    limit: int = 50


def build_postbox_router() -> APIRouter:
    router = APIRouter(tags=["postbox"])

    def _mailbox(request: Request, user: dict, claimed: str) -> str:
        return actor_username(request, user, claimed)

    @router.get("/api/postbox/status")
    def postbox_status(
        mailbox: str,
        request: Request,
        user=Depends(get_current_user),
        folder: str = FOLDER_INBOX,
    ):
        box = _mailbox(request, user, mailbox)
        return request.app.state.postbox.status(box, folder)

    @router.get("/api/postbox/messages")
    def postbox_list(
        mailbox: str,
        request: Request,
        user=Depends(get_current_user),
        folder: str = FOLDER_INBOX,
        limit: int = 50,
        unread_only: bool = False,
    ):
        box = _mailbox(request, user, mailbox)
        return {
            "mailbox": box,
            "folder": folder,
            "messages": request.app.state.postbox.list_headers(
                box, folder=folder, limit=limit, unread_only=unread_only
            ),
        }

    @router.get("/api/postbox/messages/{local_id}")
    def postbox_get(
        local_id: int,
        mailbox: str,
        request: Request,
        user=Depends(get_current_user),
        folder: str = FOLDER_INBOX,
    ):
        box = _mailbox(request, user, mailbox)
        msg = request.app.state.postbox.get(
            box, local_id=local_id, folder=folder, include_body=True
        )
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        request.app.state.postbox.mark(box, message_id=msg["id"], read=True)
        msg = request.app.state.postbox.get(
            box, message_id=msg["id"], include_body=True
        )
        return msg

    @router.post("/api/postbox/messages")
    def postbox_send(
        body: MailSend, request: Request, user=Depends(get_current_user)
    ):
        from_user = actor_username(request, user, body.from_user)
        db = request.app.state.db
        db.ensure_user(from_user)
        try:
            result = request.app.state.postbox.send(
                from_user=from_user,
                to_addr=body.to,
                subject=body.subject,
                body=body.body,
                message_id=body.message_id,
                attachment_name=body.attachment_name,
                attachment_size=body.attachment_size,
                queue_only=body.queue_only,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @router.post("/api/postbox/reply")
    def postbox_reply(
        body: MailReply, request: Request, user=Depends(get_current_user)
    ):
        from_user = actor_username(request, user, body.from_user)
        try:
            result = request.app.state.postbox.reply(
                from_user=from_user,
                local_id=body.local_id,
                body=body.body,
                folder=body.folder,
                queue_only=body.queue_only,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @router.post("/api/postbox/outbox/flush")
    def postbox_flush(
        body: MailFlush, request: Request, user=Depends(get_current_user)
    ):
        box = _mailbox(request, user, body.mailbox)
        try:
            return request.app.state.postbox.flush_outbox(
                box, local_id=body.local_id, limit=body.limit
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/postbox/mark")
    def postbox_mark(
        body: MailMark, request: Request, user=Depends(get_current_user)
    ):
        box = _mailbox(request, user, body.mailbox)
        result = request.app.state.postbox.mark(
            box,
            local_id=body.local_id,
            message_id=body.message_id,
            folder=body.folder,
            read=body.read,
            delete=body.delete,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Message not found")
        return result

    @router.get("/api/postbox/address/{username}")
    def postbox_address(username: str, user=Depends(get_current_user)):
        _ = user
        return {"username": username, "address": addr_for_user(username)}

    return router
