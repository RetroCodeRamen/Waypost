"""Finder — cross-app search, respecting every service's own privacy rules.

No store of its own: a live fan-out query across already-existing,
already-scoped per-service listings/search methods, same restraint already
applied to dashboard_routes.py's _sync_status aggregate rather than
building a new shared subsystem or search index.

Deliberately excludes Dispatch and Postbox (private by design — see
docs/security.md's "must never authorize... private Dispatch threads /
another user's Postbox") and Corkboard (its own design explicitly rules
out a merged cross-outpost view — see docs/architecture.md). Commons,
Noticeboard, Fieldbook, and Locker results all go through the exact same
visibility checks their own native listing endpoints already apply —
Finder is a new way to *find* things, never a new way to *see* them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from server.services.finder.constants import DEFAULT_LIMIT, MAX_LIMIT, OP_SEARCH
from shared.protocol.envelope import Envelope, Flags

if TYPE_CHECKING:
    from server.services.commons.service import CommonsService
    from server.services.fieldbook.service import FieldbookService
    from server.services.locker.service import LockerService
    from server.services.noticeboard.service import NoticeboardService


class FinderService:
    def __init__(
        self,
        *,
        commons: "CommonsService",
        noticeboard: "NoticeboardService",
        fieldbook: "FieldbookService",
        locker: "LockerService",
    ) -> None:
        self.commons = commons
        self.noticeboard = noticeboard
        self.fieldbook = fieldbook
        self.locker = locker

    def search(
        self, query: str, *, username: Optional[str] = None, limit: int = DEFAULT_LIMIT
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        limit = max(1, min(int(limit), MAX_LIMIT))
        q_lower = query.lower()
        results: list[dict[str, Any]] = []

        for post in self.commons.search_posts(query, username=username, limit=limit):
            body = post.get("body") or ""
            results.append(
                self._normalize(
                    service="commons",
                    item_id=post["id"],
                    title=post.get("title") or body[:60],
                    snippet=self._snippet(body),
                    updated_at=post["created_at"],
                    url=f"/commons.html#{post['id']}",
                    match="title" if post.get("title_hit") else "body",
                )
            )

        for notice in self.noticeboard.search(query, username=username, limit=limit):
            results.append(
                self._normalize(
                    service="noticeboard",
                    item_id=notice["id"],
                    title=notice["title"],
                    snippet=self._snippet(notice.get("body") or ""),
                    updated_at=notice["created_at"],
                    url=f"/noticeboard.html#{notice['id']}",
                    match="title" if notice.get("title_hit") else "body",
                )
            )

        for page in self.fieldbook.search(query, limit=limit):
            results.append(
                self._normalize(
                    service="fieldbook",
                    item_id=page["slug"],
                    title=page["title"],
                    snippet=page.get("snippet") or "",
                    updated_at=page["updated_at"],
                    url=f"/fieldbook.html?slug={page['slug']}",
                    match=page.get("match") or "body",
                )
            )

        # Locker has no text search of its own — its result set is already
        # scope-filtered down to what this viewer can see, small enough
        # that filtering client-side here is simpler than adding a store
        # method just for this.
        for item in self.locker.list_files(viewer=username, limit=200):
            filename = item.get("filename") or ""
            note = item.get("note") or ""
            if q_lower not in filename.lower() and q_lower not in note.lower():
                continue
            results.append(
                self._normalize(
                    service="locker",
                    item_id=item["id"],
                    title=filename,
                    snippet=note,
                    updated_at=item["created_at"],
                    url=f"/locker.html?file={item['id']}",
                    match="title" if q_lower in filename.lower() else "body",
                )
            )

        results.sort(key=lambda r: (0 if r["match"] == "title" else 1, -r["updated_at"]))
        return results[:limit]

    async def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        if op != OP_SEARCH:
            return envelope.make_response(
                op=op, payload={"error": f"unknown_op:{op}"}, flags=Flags.RESPONSE, error=True
            )
        # Waylink has no session — search is scoped by whatever the caller
        # claims as their username, same openness as other read-only ops
        # (NOTICE_LIST etc.) that annotate but don't gate on it; the real
        # privacy boundary is each underlying service's own visibility
        # check, not who's asking here.
        results = self.search(
            str(payload.get("q") or payload.get("query") or ""),
            username=payload.get("username"),
            limit=int(payload.get("limit") or DEFAULT_LIMIT),
        )
        # Bandwidth philosophy: titles + snippets only, never full bodies
        # or file contents — matches Locker's own "metadata only over
        # Waylink" precedent.
        return envelope.make_response(op=op, payload={"results": results})

    @staticmethod
    def _normalize(
        *,
        service: str,
        item_id: str,
        title: str,
        snippet: str,
        updated_at: float,
        url: str,
        match: str,
    ) -> dict[str, Any]:
        return {
            "service": service,
            "id": item_id,
            "title": title,
            "snippet": snippet,
            "updated_at": updated_at,
            "url": url,
            "match": match,
        }

    @staticmethod
    def _snippet(text: str, *, chars: int = 160) -> str:
        text = " ".join((text or "").split())
        if len(text) <= chars:
            return text
        return text[:chars].rstrip() + "…"
