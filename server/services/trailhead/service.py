"""Trailhead — the Station's small web of linked text pages.

Gemini/gopher-style rather than HTML (docs/naming.md: Waylink is compact
RPC over radio, not HTML over LoRa). One construct per line:

    # Heading            (also ## / ###)
    => path Link label   (link to another Trailhead page)
    anything else        (plain text, wrapped by the reader)

Pages are edited in the Station portal and read anywhere: the portal over
Wi-Fi, a Scout over LoRa via TRAIL_GET in ~160-byte chunks.
Reads are open (community pages, like Fieldbook reads); writes are portal
only, by a signed-in user.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from server.services.trailhead.constants import (
    HOME_PATH,
    MAX_BODY,
    MAX_PATH,
    MAX_TITLE,
    OP_TRAIL_GET,
)
from server.services.trailhead.store import TrailheadStore
from shared.protocol.envelope import Envelope, Flags
from shared.protocol.radio import CHUNK_DEFAULT, chunk_utf8, fit_text_reply

_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*$")

SEED_PAGES = [
    (
        HOME_PATH,
        "Trailhead",
        """# Welcome to Trailhead
These pages live on this camp's Waypost Station. Read them on the portal, or on a Scout over the radio.

=> getting-started Getting started
=> camp-info Camp info

Station operators can edit these pages from the portal.""",
    ),
    (
        "getting-started",
        "Getting started",
        """# Getting started
On a Scout, roll the trackball to pick a link and press it to open the page. Roll left to go back.

Pages load a little at a time over the radio, so short pages read best.

=> home Back to Trailhead""",
    ),
    (
        "camp-info",
        "Camp info",
        """# Camp info
Edit this page from the Station portal: meeting times, water, quiet hours, who to ask for help.

=> home Back to Trailhead""",
    ),
]


class TrailheadService:
    def __init__(self, store: TrailheadStore) -> None:
        self.store = store

    def seed_defaults(self) -> None:
        """First run only: give a fresh Station something to browse."""
        if self.store.count_pages() > 0:
            return
        for path, title, body in SEED_PAGES:
            self.store.put_page(path=path, title=title, body=body, author="station")

    # -- reads -------------------------------------------------------------

    def list_pages(self) -> list[dict[str, Any]]:
        return self.store.list_pages()

    def get_page(self, path: str) -> Optional[dict[str, Any]]:
        return self.store.get_page(self.normalize_path(path))

    # -- writes ------------------------------------------------------------

    def save_page(self, path: str, *, title: str, body: str, author: str) -> dict[str, Any]:
        path = self.check_path(path)
        title = (title or "").strip()
        if not title or len(title) > MAX_TITLE:
            raise ValueError(f"title required (max {MAX_TITLE})")
        body = (body or "").replace("\r\n", "\n")
        if len(body) > MAX_BODY:
            raise ValueError(f"body too long (max {MAX_BODY})")
        author = (author or "").strip()
        if not author:
            raise ValueError("author required")
        return self.store.put_page(path=path, title=title, body=body, author=author)

    def delete_page(self, path: str) -> bool:
        return self.store.delete_page(self.normalize_path(path))

    @staticmethod
    def normalize_path(path: str) -> str:
        return (path or "").strip().strip("/").lower()

    def check_path(self, path: str) -> str:
        p = self.normalize_path(path)
        if not p or len(p) > MAX_PATH or not _PATH_RE.match(p):
            raise ValueError("invalid path (a-z, 0-9, -, _, /)")
        return p

    # -- Waylink -----------------------------------------------------------

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        if envelope.op != OP_TRAIL_GET:
            return envelope.make_response(
                op=envelope.op,
                payload={"error": f"unknown_op:{envelope.op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        page = self.get_page(str(payload.get("path") or HOME_PATH))
        if not page:
            return envelope.make_response(
                op=envelope.op, payload={"error": "not_found"}, error=True
            )
        try:
            offset = max(0, int(payload.get("offset") or 0))
            limit = int(payload.get("limit") or CHUNK_DEFAULT)
        except (TypeError, ValueError):
            return envelope.make_response(
                op=envelope.op, payload={"error": "invalid_payload"}, error=True
            )
        _, total = chunk_utf8(page["body"], 0, 0)

        def build(piece: str) -> Envelope:
            body: dict[str, Any] = {
                "path": page["path"],
                "offset": offset,
                "total": total,
                "text": piece,
            }
            if offset == 0:
                body["title"] = page["title"][:40]
            return envelope.make_response(op=envelope.op, payload=body)

        return fit_text_reply(build, page["body"], offset, limit)
