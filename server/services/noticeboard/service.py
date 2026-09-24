"""Noticeboard service — structured community bulletins."""

from __future__ import annotations

from typing import Any, Callable, Optional

from server.services.noticeboard.constants import (
    MAX_BODY,
    MAX_TITLE,
    OP_NOTICE_ACK,
    OP_NOTICE_CREATE,
    OP_NOTICE_EXPIRE,
    OP_NOTICE_GET,
    OP_NOTICE_LIST,
)
from server.services.noticeboard.store import NoticeStore
from shared.protocol.envelope import Envelope, Flags

ALLOWED_PRIORITY = {"normal", "high", "low"}


class NoticeboardService:
    def __init__(
        self,
        store: NoticeStore,
        *,
        get_binding: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    ) -> None:
        self.store = store
        # Injected rather than importing DispatchStore directly — same
        # cross-service lookup pattern as PostboxService.set_nodes_lookup.
        # Resolves a radio node_id to its bound account, so NOTICE_CREATE/
        # ACK/EXPIRE over Waylink can't have their author/actor spoofed by
        # whatever the packet's own payload claims.
        self._get_binding = get_binding or (lambda _node_id: None)

    def _bound_username(self, node_id: str) -> Optional[str]:
        binding = self._get_binding(node_id)
        return str(binding["username"]) if binding else None

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

    def list_notices(
        self, *, active_only: bool = True, limit: int = 50, username: Optional[str] = None
    ) -> list[dict[str, Any]]:
        return self.store.list_notices(active_only=active_only, limit=limit, username=username)

    def get(self, notice_id: str, *, username: Optional[str] = None) -> Optional[dict[str, Any]]:
        return self.store.get(notice_id, username=username)

    def expire(self, notice_id: str) -> Optional[dict[str, Any]]:
        return self.store.expire(notice_id)

    def count_active(self) -> int:
        return self.store.count_active()

    def ack(self, notice_id: str, username: str) -> dict[str, Any]:
        username = username.strip()
        if not username:
            raise ValueError("username required")
        if not self.store.get(notice_id):
            raise ValueError("notice not found")
        self.store.ack(notice_id, username)
        return {"id": notice_id, "acked": True}

    def count_unacked(self, username: str) -> int:
        return self.store.count_unacked_active(username)

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_NOTICE_LIST:
                # Read-only: annotate with this device's own ack state when
                # it's bound to someone, but don't require binding just to
                # read the board (same openness as HTTP GET today).
                notices = self.list_notices(
                    active_only=bool(payload.get("active_only", True)),
                    limit=int(payload.get("limit") or 50),
                    username=self._bound_username(envelope.src),
                )
                return envelope.make_response(op=op, payload={"notices": notices})
            if op == OP_NOTICE_GET:
                notice = self.get(
                    str(payload.get("id") or ""),
                    username=self._bound_username(envelope.src),
                )
                if not notice:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_CREATE:
                author = self._bound_username(envelope.src)
                if not author:
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                notice = self.create(
                    author=author,
                    title=str(payload.get("title") or ""),
                    body=str(payload.get("body") or ""),
                    priority=str(payload.get("priority") or "normal"),
                    expires_at=payload.get("expires_at"),
                    notice_id=payload.get("id"),
                )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_EXPIRE:
                if not self._bound_username(envelope.src):
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                notice = self.expire(str(payload.get("id") or ""))
                if not notice:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_ACK:
                username = self._bound_username(envelope.src)
                if not username:
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                try:
                    result = self.ack(str(payload.get("id") or ""), username)
                except ValueError as exc:
                    return envelope.make_response(
                        op=op, payload={"error": str(exc)}, error=True
                    )
                return envelope.make_response(op=op, payload=result)
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except ValueError as exc:
            return envelope.make_response(op=op, payload={"error": str(exc)}, error=True)
