"""Commons service — community social feed."""

from __future__ import annotations

from typing import Any, Callable, Optional

from server.services.commons.constants import (
    MAX_BODY,
    MAX_TITLE,
    OP_POST_CREATE,
    OP_POST_GET,
    OP_POST_LIST,
)
from server.services.commons.store import CommonsStore
from shared.protocol.envelope import Envelope, Flags


class CommonsService:
    def __init__(
        self,
        store: CommonsStore,
        *,
        is_group_member: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self.store = store
        self._is_group_member = is_group_member or (lambda _gid, _username: False)

    def _can_view(self, post: dict[str, Any], viewer: Optional[str]) -> bool:
        gid = post.get("group_id")
        if not gid:
            return True
        if not viewer:
            return False
        return self._is_group_member(gid, viewer)

    def create(
        self,
        *,
        author: str,
        body: str,
        title: str = "",
        post_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> dict[str, Any]:
        author = author.strip()
        body = (body or "").strip()
        title = (title or "").strip()
        group_id = (group_id or "").strip() or None
        if not author:
            raise ValueError("author required")
        if not body:
            raise ValueError("body required")
        if len(body) > MAX_BODY:
            raise ValueError(f"body too long (max {MAX_BODY})")
        if len(title) > MAX_TITLE:
            raise ValueError(f"title too long (max {MAX_TITLE})")
        if group_id and not self._is_group_member(group_id, author):
            raise ValueError("author must be a member of the group")
        return self.store.create(
            author=author,
            body=body,
            title=title,
            post_id=post_id,
            group_id=group_id,
        )

    def list_posts(
        self,
        *,
        limit: int = 50,
        since: Optional[float] = None,
        username: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        group_id = (group_id or "").strip() or None
        if group_id and username and not self._is_group_member(group_id, username):
            return []
        rows = self.store.list_posts(limit=500, since=since, group_id=group_id)
        out: list[dict[str, Any]] = []
        cap = max(1, min(int(limit), 200))
        for post in rows:
            if not self._can_view(post, username):
                continue
            out.append(post)
            if len(out) >= cap:
                break
        return out

    def get(self, post_id: str, *, username: Optional[str] = None) -> Optional[dict[str, Any]]:
        post = self.store.get(post_id)
        if not post or not self._can_view(post, username):
            return None
        return post

    def recent_count(
        self,
        *,
        hours: float = 24.0,
        exclude_author: Optional[str] = None,
        username: Optional[str] = None,
    ) -> int:
        import time

        since = time.time() - (hours * 3600)
        if username is None:
            return self.store.count_recent(since=since, exclude_author=exclude_author)
        visible = self.list_posts(limit=500, since=since, username=username)
        if exclude_author:
            exclude = exclude_author.lower()
            visible = [p for p in visible if p.get("author", "").lower() != exclude]
        return len(visible)

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_POST_LIST:
                posts = self.list_posts(
                    limit=int(payload.get("limit") or 50),
                    since=payload.get("since"),
                    username=str(payload.get("viewer") or "") or None,
                    group_id=payload.get("group_id"),
                )
                return envelope.make_response(op=op, payload={"posts": posts})
            if op == OP_POST_CREATE:
                post = self.create(
                    author=str(payload.get("author") or envelope.src or ""),
                    body=str(payload.get("body") or ""),
                    title=str(payload.get("title") or ""),
                    post_id=payload.get("id"),
                    group_id=payload.get("group_id"),
                )
                return envelope.make_response(op=op, payload={"post": post})
            if op == OP_POST_GET:
                post = self.get(
                    str(payload.get("id") or ""),
                    username=str(payload.get("viewer") or "") or None,
                )
                if not post:
                    return envelope.make_response(
                        op=op,
                        payload={"error": "not_found"},
                        error=True,
                    )
                return envelope.make_response(op=op, payload={"post": post})
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except ValueError as exc:
            return envelope.make_response(
                op=op,
                payload={"error": str(exc)},
                error=True,
            )
