"""Fieldbook service — the editable community wiki, built for the progressive path.

Bandwidth philosophy (docs/architecture.md): search → page → section/diff. Over
Waylink a Pocket asks for compact search hits, then a page *outline*, then one
section — or, if it already holds revision N, just the diff since N. Edits carry
the base revision they were made against; a mismatch returns the current
revision instead of silently overwriting (docs/protocol.md "Fieldbook").

Same radio-authz shape as Noticeboard: reads are open, writes resolve the
author from the sending device's binding, never from the payload.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Callable, Optional

from server.services.fieldbook.constants import (
    MAX_BODY,
    MAX_SLUG,
    MAX_SUMMARY,
    MAX_TITLE,
    OP_WIKI_CREATE,
    OP_WIKI_GET,
    OP_WIKI_SEARCH,
    OP_WIKI_UPDATE,
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    SNIPPET_CHARS,
)
from server.services.fieldbook.store import FieldbookStore
from shared.protocol.envelope import Envelope, Flags

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class RevisionConflict(Exception):
    """Edit was based on a stale revision. Carries the page as it is now."""

    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("revision_conflict")
        self.current = current


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:MAX_SLUG].strip("-")


def split_sections(body: str) -> list[dict[str, Any]]:
    """Split Markdown-ish text on ATX headings. Section 0 is any preamble
    before the first heading (omitted when empty). Each section's `text`
    includes its heading line, so sections concatenate back to the body."""
    lines = (body or "").split("\n")
    sections: list[dict[str, Any]] = []
    cur_lines: list[str] = []
    cur_heading = ""
    cur_level = 0
    started = False

    def flush() -> None:
        text = "\n".join(cur_lines)
        if not started and not text.strip():
            return
        sections.append(
            {
                "index": len(sections),
                "heading": cur_heading,
                "level": cur_level,
                "text": text,
                "size": len(text),
            }
        )

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            cur_lines = [line]
            cur_heading = m.group(2).strip()
            cur_level = len(m.group(1))
            started = True
        else:
            cur_lines.append(line)
    flush()
    return sections


def join_sections(sections: list[dict[str, Any]]) -> str:
    return "\n".join(s["text"] for s in sections)


def outline_of(body: str) -> list[dict[str, Any]]:
    return [
        {"index": s["index"], "heading": s["heading"], "level": s["level"], "size": s["size"]}
        for s in split_sections(body)
    ]


class FieldbookService:
    def __init__(
        self,
        store: FieldbookStore,
        *,
        get_binding: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    ) -> None:
        self.store = store
        self._get_binding = get_binding or (lambda _node_id: None)

    def _bound_username(self, node_id: str) -> Optional[str]:
        binding = self._get_binding(node_id)
        return str(binding["username"]) if binding else None

    # -- validation --------------------------------------------------------

    @staticmethod
    def _check_slug(slug: str) -> str:
        slug = (slug or "").strip().lower()
        if not slug:
            raise ValueError("slug required")
        if len(slug) > MAX_SLUG or not _SLUG_RE.match(slug):
            raise ValueError("slug must be lowercase letters, digits and dashes")
        return slug

    @staticmethod
    def _check_title(title: str) -> str:
        title = (title or "").strip()
        if not title:
            raise ValueError("title required")
        if len(title) > MAX_TITLE:
            raise ValueError(f"title too long (max {MAX_TITLE})")
        return title

    @staticmethod
    def _check_body(body: str) -> str:
        body = (body or "").replace("\r\n", "\n").strip("\n")
        if len(body) > MAX_BODY:
            raise ValueError(f"body too long (max {MAX_BODY})")
        return body

    @staticmethod
    def _check_summary(summary: Optional[str]) -> str:
        summary = (summary or "").strip()
        if len(summary) > MAX_SUMMARY:
            raise ValueError(f"summary too long (max {MAX_SUMMARY})")
        return summary

    # -- reads -------------------------------------------------------------

    def list_pages(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_pages(limit=limit)

    def recent_pages(self, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.store.recent_pages(limit=limit)

    def count_pages(self) -> int:
        return self.store.count_pages()

    def get_page(self, slug: str) -> Optional[dict[str, Any]]:
        return self.store.get_page(slug)

    def get_outline(self, slug: str) -> Optional[dict[str, Any]]:
        page = self.store.get_page(slug)
        if not page:
            return None
        return {
            "slug": page["slug"],
            "title": page["title"],
            "revision": page["revision"],
            "updated_by": page["updated_by"],
            "updated_at": page["updated_at"],
            "size": page["size"],
            "outline": outline_of(page["body"]),
        }

    def get_section(self, slug: str, section: Any) -> Optional[dict[str, Any]]:
        """`section` is an index or a heading (case-insensitive). None when
        the page or section doesn't exist."""
        page = self.store.get_page(slug)
        if not page:
            return None
        found = self._find_section(page["body"], section)
        if found is None:
            return None
        return {
            "slug": page["slug"],
            "title": page["title"],
            "revision": page["revision"],
            "section": found,
        }

    @staticmethod
    def _find_section(body: str, section: Any) -> Optional[dict[str, Any]]:
        sections = split_sections(body)
        if isinstance(section, bool):
            return None
        if isinstance(section, int) or (isinstance(section, str) and section.strip().isdigit()):
            idx = int(section)
            return sections[idx] if 0 <= idx < len(sections) else None
        want = str(section or "").strip().lower()
        if not want:
            return None
        for s in sections:
            if s["heading"].lower() == want:
                return s
        return None

    def diff(self, slug: str, from_revision: int, to_revision: Optional[int] = None) -> Optional[dict[str, Any]]:
        page = self.store.get_page(slug)
        if not page:
            return None
        to_rev = int(to_revision) if to_revision is not None else int(page["revision"])
        old = self.store.get_revision(slug, int(from_revision))
        new = page if to_rev == page["revision"] else self.store.get_revision(slug, to_rev)
        if not old or not new:
            return None
        # Bodies are stored without a trailing newline; add one so the final
        # line diffs as a whole line instead of gluing onto the next marker.
        udiff = "".join(
            difflib.unified_diff(
                (old["body"] + "\n").splitlines(keepends=True),
                (new["body"] + "\n").splitlines(keepends=True),
                fromfile=f"{slug}@{old['revision']}",
                tofile=f"{slug}@{new['revision']}",
                n=2,
            )
        )
        return {
            "slug": slug,
            "title": new["title"],
            "from_revision": int(old["revision"]),
            "to_revision": int(new["revision"]),
            "unchanged": int(old["revision"]) == int(new["revision"]),
            "diff": udiff,
        }

    def history(self, slug: str, *, limit: int = 50) -> Optional[list[dict[str, Any]]]:
        if not self.store.get_page(slug):
            return None
        return self.store.list_revisions(slug, limit=limit)

    def get_revision(self, slug: str, revision: int) -> Optional[dict[str, Any]]:
        return self.store.get_revision(slug, revision)

    def search(self, query: str, *, limit: int = SEARCH_LIMIT_DEFAULT) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or SEARCH_LIMIT_DEFAULT), SEARCH_LIMIT_MAX))
        q = (query or "").strip()
        if not q:
            return []
        out = []
        for hit in self.store.search(q, limit=limit):
            body = hit.pop("body")
            title_hit = hit.pop("title_hit")
            body_hit = hit.pop("body_hit")
            hit["match"] = "title" if title_hit else "body"
            hit["snippet"] = self._snippet(body, body_hit)
            out.append(hit)
        return out

    @staticmethod
    def _snippet(body: str, hit_pos: int) -> str:
        text = " ".join(body.split())
        if not text:
            return ""
        if hit_pos <= 0:
            return text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else "")
        # instr() is 1-based on the raw body; the whitespace-collapsed text
        # shifts positions, so re-find in the collapsed form and fall back.
        raw_needle = body[hit_pos - 1 : hit_pos - 1 + 24]
        needle = " ".join(raw_needle.split())
        pos = text.lower().find(needle.lower()) if needle else -1
        if pos < 0:
            pos = 0
        start = max(0, pos - SNIPPET_CHARS // 3)
        end = min(len(text), start + SNIPPET_CHARS)
        return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")

    # -- writes ------------------------------------------------------------

    def create_page(
        self,
        *,
        author: str,
        title: str,
        body: str,
        slug: Optional[str] = None,
        summary: str = "",
    ) -> dict[str, Any]:
        author = (author or "").strip()
        if not author:
            raise ValueError("author required")
        title = self._check_title(title)
        slug = self._check_slug(slug or slugify(title))
        body = self._check_body(body)
        summary = self._check_summary(summary) or "created"
        if self.store.get_page(slug):
            raise FileExistsError("page already exists")
        return self.store.create_page(
            slug=slug, title=title, body=body, author=author, summary=summary
        )

    def update_page(
        self,
        slug: str,
        *,
        author: str,
        base_revision: int,
        body: Optional[str] = None,
        title: Optional[str] = None,
        section: Any = None,
        section_text: Optional[str] = None,
        summary: str = "",
    ) -> dict[str, Any]:
        """Save a new revision. Either a whole `body`, or one `section`
        replaced with `section_text` (the LoRa-friendly path). Raises
        RevisionConflict when `base_revision` isn't the current one."""
        author = (author or "").strip()
        if not author:
            raise ValueError("author required")
        slug = self._check_slug(slug)
        summary = self._check_summary(summary)
        page = self.store.get_page(slug)
        if not page:
            raise ValueError("page not found")
        try:
            base = int(base_revision)
        except (TypeError, ValueError) as exc:
            raise ValueError("base_revision required") from exc
        if base != int(page["revision"]):
            raise RevisionConflict(page)

        new_title = self._check_title(title) if title is not None else page["title"]
        if section is not None:
            if section_text is None:
                raise ValueError("section_text required with section")
            sections = split_sections(page["body"])
            target = self._find_section(page["body"], section)
            if target is None:
                raise ValueError("section not found")
            replacement = self._check_body(section_text)
            sections[target["index"]]["text"] = replacement
            new_body = self._check_body(join_sections(sections))
        elif body is not None:
            new_body = self._check_body(body)
        else:
            raise ValueError("body or section required")

        if new_body == page["body"] and new_title == page["title"]:
            return page
        return self.store.save_revision(
            slug=slug, title=new_title, body=new_body, author=author, summary=summary
        )

    # -- Waylink -----------------------------------------------------------

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_WIKI_SEARCH:
                results = self.search(
                    str(payload.get("q") or payload.get("query") or ""),
                    limit=int(payload.get("limit") or SEARCH_LIMIT_DEFAULT),
                )
                return envelope.make_response(op=op, payload={"results": results})
            if op == OP_WIKI_GET:
                return self._rpc_get(envelope, payload)
            if op == OP_WIKI_CREATE:
                author = self._bound_username(envelope.src)
                if not author:
                    return self._err(envelope, "unauthorized_device")
                try:
                    page = self.create_page(
                        author=author,
                        title=str(payload.get("title") or ""),
                        body=str(payload.get("body") or ""),
                        slug=payload.get("slug"),
                        summary=str(payload.get("summary") or ""),
                    )
                except FileExistsError:
                    return self._err(envelope, "already_exists")
                return envelope.make_response(op=op, payload={"page": self._compact(page)})
            if op == OP_WIKI_UPDATE:
                author = self._bound_username(envelope.src)
                if not author:
                    return self._err(envelope, "unauthorized_device")
                try:
                    page = self.update_page(
                        str(payload.get("slug") or ""),
                        author=author,
                        base_revision=payload.get("base_revision"),
                        body=payload.get("body"),
                        title=payload.get("title"),
                        section=payload.get("section"),
                        section_text=payload.get("section_text"),
                        summary=str(payload.get("summary") or ""),
                    )
                except RevisionConflict as conflict:
                    # Send what a Pocket needs to rebase — revision + outline —
                    # not the whole current body over the air.
                    cur = conflict.current
                    return envelope.make_response(
                        op=op,
                        payload={
                            "error": "revision_conflict",
                            "slug": cur["slug"],
                            "current_revision": cur["revision"],
                            "updated_by": cur["updated_by"],
                            "outline": outline_of(cur["body"]),
                        },
                        error=True,
                    )
                return envelope.make_response(op=op, payload={"page": self._compact(page)})
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except ValueError as exc:
            return self._err(envelope, str(exc))

    def _rpc_get(self, envelope: Envelope, payload: dict[str, Any]) -> Envelope:
        op = envelope.op
        slug = str(payload.get("slug") or "")
        page = self.store.get_page(slug)
        if not page:
            return self._err(envelope, "not_found")

        since = payload.get("since")
        if since is not None:
            if int(since) == int(page["revision"]):
                return envelope.make_response(
                    op=op,
                    payload={"slug": slug, "revision": page["revision"], "unchanged": True},
                )
            d = self.diff(slug, int(since))
            if d is not None:
                return envelope.make_response(op=op, payload=d)
            # Unknown base revision — fall through to a full page.

        if payload.get("section") is not None:
            found = self.get_section(slug, payload.get("section"))
            if not found:
                return self._err(envelope, "section_not_found")
            return envelope.make_response(op=op, payload=found)

        if payload.get("outline"):
            return envelope.make_response(op=op, payload=self.get_outline(slug))

        return envelope.make_response(op=op, payload={"page": page})

    @staticmethod
    def _compact(page: dict[str, Any]) -> dict[str, Any]:
        """Write acks don't need the body echoed back over the radio."""
        return {k: v for k, v in page.items() if k != "body"}

    @staticmethod
    def _err(envelope: Envelope, error: str) -> Envelope:
        return envelope.make_response(op=envelope.op, payload={"error": error}, error=True)
