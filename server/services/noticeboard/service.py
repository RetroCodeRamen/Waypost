"""Noticeboard service — structured community bulletins."""

from __future__ import annotations

from typing import Any, Optional

from server.services.noticeboard.constants import (
    MAX_BODY,
    MAX_TITLE,
    OP_NOTICE_CREATE,
    OP_NOTICE_EXPIRE,
    OP_NOTICE_GET,
    OP_NOTICE_LIST,
)
from server.services.noticeboard.store import NoticeStore
from shared.protocol.envelope import Envelope, Flags

ALLOWED_PRIORITY = {"normal", "high", "low"}


class NoticeboardService:
    def __init__(self, store: NoticeStore) -> None:
        self.store = store

    def create(
        self,
        *,
        author: str,
        title: str,
        body: str,
        priority: str = "normal",
        expires_at: Optional[float] = None,
        notice_id: Optional[str] = None,
    ) -> dict[str, Any]:
        author = author.strip()
        title = (title or "").strip()
        body = (body or "").strip()
        priority = (priority or "normal").strip().lower()
        if not author:
            raise ValueError("author required")
        if not title:
            raise ValueError("title required")
        if not body:
            raise ValueError("body required")
        if len(title) > MAX_TITLE:
            raise ValueError(f"title too long (max {MAX_TITLE})")
        if len(body) > MAX_BODY:
            raise ValueError(f"body too long (max {MAX_BODY})")
        if priority not in ALLOWED_PRIORITY:
            raise ValueError("priority must be normal, high, or low")
        return self.store.create(
            author=author,
            title=title,
            body=body,
            priority=priority,
            expires_at=expires_at,
            notice_id=notice_id,
        )

    def list_notices(self, *, active_only: bool = True, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_notices(active_only=active_only, limit=limit)

    def get(self, notice_id: str) -> Optional[dict[str, Any]]:
        return self.store.get(notice_id)

    def expire(self, notice_id: str) -> Optional[dict[str, Any]]:
        return self.store.expire(notice_id)

    def count_active(self) -> int:
        return self.store.count_active()

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_NOTICE_LIST:
                notices = self.list_notices(
                    active_only=bool(payload.get("active_only", True)),
                    limit=int(payload.get("limit") or 50),
                )
                return envelope.make_response(op=op, payload={"notices": notices})
            if op == OP_NOTICE_GET:
                notice = self.get(str(payload.get("id") or ""))
                if not notice:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_CREATE:
                notice = self.create(
                    author=str(payload.get("author") or envelope.src or ""),
                    title=str(payload.get("title") or ""),
                    body=str(payload.get("body") or ""),
                    priority=str(payload.get("priority") or "normal"),
                    expires_at=payload.get("expires_at"),
                    notice_id=payload.get("id"),
                )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_EXPIRE:
                notice = self.expire(str(payload.get("id") or ""))
                if not notice:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"notice": notice})
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except ValueError as exc:
            return envelope.make_response(op=op, payload={"error": str(exc)}, error=True)
