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
        is_group_member: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self.store = store
        self._get_binding = get_binding or (lambda _node_id: None)
        self._is_group_member = is_group_member or (lambda _gid, _username: False)

    def _bound_username(self, node_id: str) -> Optional[str]:
        binding = self._get_binding(node_id)
        return str(binding["username"]) if binding else None

    def _can_view(self, notice: dict[str, Any], viewer: Optional[str]) -> bool:
        gid = notice.get("group_id")
        if not gid:
            return True
        if not viewer:
            return False
        return self._is_group_member(gid, viewer)

    def create(
        self,
        *,
        author: str,
        title: str,
        body: str,
        priority: str = "normal",
        expires_at: Optional[float] = None,
        notice_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> dict[str, Any]:
        author = author.strip()
        title = (title or "").strip()
        body = (body or "").strip()
        priority = (priority or "normal").strip().lower()
        group_id = (group_id or "").strip() or None
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
        if group_id and not self._is_group_member(group_id, author):
            raise ValueError("author must be a member of the group")
        return self.store.create(
            author=author,
            title=title,
            body=body,
            priority=priority,
            expires_at=expires_at,
            notice_id=notice_id,
            group_id=group_id,
        )

    def list_notices(
        self,
        *,
        active_only: bool = True,
        limit: int = 50,
        username: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        group_id = (group_id or "").strip() or None
        if group_id and username and not self._is_group_member(group_id, username):
            return []
        rows = self.store.list_notices(
            active_only=active_only,
            limit=500,
            username=username,
            group_id=group_id,
        )
        out: list[dict[str, Any]] = []
        cap = max(1, min(int(limit), 200))
        for notice in rows:
            if not self._can_view(notice, username):
                continue
            out.append(notice)
            if len(out) >= cap:
                break
        return out

    def get(self, notice_id: str, *, username: Optional[str] = None) -> Optional[dict[str, Any]]:
        notice = self.store.get(notice_id, username=username)
        if not notice or not self._can_view(notice, username):
            return None
        return notice

    def search(
        self, query: str, *, username: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        rows = self.store.search(query, limit=500, username=username)
        out: list[dict[str, Any]] = []
        cap = max(1, min(int(limit), 200))
        for notice in rows:
            if not self._can_view(notice, username):
                continue
            out.append(notice)
            if len(out) >= cap:
                break
        return out

    def expire(
        self, notice_id: str, *, username: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        notice = self.store.get(notice_id)
        if not notice or not self._can_view(notice, username):
            return None
        return self.store.expire(notice_id)

    def count_active(self, *, username: Optional[str] = None) -> int:
        if username is None:
            return self.store.count_active()
        return len(self.list_notices(active_only=True, limit=200, username=username))

    def ack(self, notice_id: str, username: str) -> dict[str, Any]:
        username = username.strip()
        if not username:
            raise ValueError("username required")
        notice = self.get(notice_id, username=username)
        if not notice:
            raise ValueError("notice not found")
        self.store.ack(notice_id, username)
        return {"id": notice_id, "acked": True}

    def count_unacked(self, username: str) -> int:
        username = username.strip()
        visible = self.list_notices(active_only=True, limit=200, username=username)
        acked_ids = self.store.acked_ids_for(username)
        return sum(1 for n in visible if n["id"] not in acked_ids)

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        viewer = self._bound_username(envelope.src)
        try:
            if op == OP_NOTICE_LIST:
                notices = self.list_notices(
                    active_only=bool(payload.get("active_only", True)),
                    limit=int(payload.get("limit") or 50),
                    username=viewer,
                    group_id=payload.get("group_id"),
                )
                return envelope.make_response(op=op, payload={"notices": notices})
            if op == OP_NOTICE_GET:
                notice = self.get(str(payload.get("id") or ""), username=viewer)
                if not notice:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_CREATE:
                author = viewer
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
                    group_id=payload.get("group_id"),
                )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_EXPIRE:
                if not viewer:
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                notice = self.expire(str(payload.get("id") or ""), username=viewer)
                if not notice:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"notice": notice})
            if op == OP_NOTICE_ACK:
                if not viewer:
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                try:
                    result = self.ack(str(payload.get("id") or ""), viewer)
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
