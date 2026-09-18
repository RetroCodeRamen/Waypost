"""Commons service — community social feed."""

from __future__ import annotations

from typing import Any, Optional

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
    def __init__(self, store: CommonsStore) -> None:
        self.store = store

    def create(
        self,
        *,
        author: str,
        body: str,
        title: str = "",
        post_id: Optional[str] = None,
    ) -> dict[str, Any]:
        author = author.strip()
        body = (body or "").strip()
        title = (title or "").strip()
        if not author:
            raise ValueError("author required")
        if not body:
            raise ValueError("body required")
        if len(body) > MAX_BODY:
            raise ValueError(f"body too long (max {MAX_BODY})")
        if len(title) > MAX_TITLE:
            raise ValueError(f"title too long (max {MAX_TITLE})")
        return self.store.create(
            author=author,
            body=body,
            title=title,
            post_id=post_id,
        )

    def list_posts(self, *, limit: int = 50, since: Optional[float] = None) -> list[dict[str, Any]]:
        return self.store.list_posts(limit=limit, since=since)

    def get(self, post_id: str) -> Optional[dict[str, Any]]:
        return self.store.get(post_id)

    def recent_count(self, *, hours: float = 24.0, exclude_author: Optional[str] = None) -> int:
        import time

        since = time.time() - (hours * 3600)
        return self.store.count_recent(since=since, exclude_author=exclude_author)

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_POST_LIST:
                posts = self.list_posts(
                    limit=int(payload.get("limit") or 50),
                    since=payload.get("since"),
                )
                return envelope.make_response(op=op, payload={"posts": posts})
            if op == OP_POST_CREATE:
                post = self.create(
                    author=str(payload.get("author") or envelope.src or ""),
                    body=str(payload.get("body") or ""),
                    title=str(payload.get("title") or ""),
                    post_id=payload.get("id"),
                )
                return envelope.make_response(op=op, payload={"post": post})
            if op == OP_POST_GET:
                post = self.get(str(payload.get("id") or ""))
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
