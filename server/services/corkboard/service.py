"""Corkboard service — per-outpost public note board.

Trust model is deliberately different from Dispatch/Noticeboard: authorship
is a free-text signature, not an account, matching the walk-up-at-the-
Outpost's-own-Wi-Fi use case this exists for (see docs/architecture.md).
"""

from __future__ import annotations

from typing import Any, Optional

from server.services.corkboard.constants import (
    MAX_BODY,
    MAX_DISPLAY_NAME,
    MAX_SIGNATURE,
    OP_BOARD_SYNC,
)
from server.services.corkboard.store import CorkboardStore
from shared.protocol.envelope import Envelope, Flags


class CorkboardService:
    def __init__(self, store: CorkboardStore) -> None:
        self.store = store

    def list_outposts(self) -> list[dict[str, Any]]:
        return self.store.list_outposts()

    def list_notes(self, outpost_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_notes(outpost_id, limit=limit)

    def post_note(
        self,
        *,
        outpost_id: str,
        body: str,
        signature: Optional[str],
        note_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Queue a Station-composed note for a specific outpost. Not
        delivered by this slice — that needs the Outpost-side sync method,
        which doesn't exist yet; this just makes sure the note is waiting
        the moment it does."""
        outpost_id = (outpost_id or "").strip()
        body = (body or "").strip()
        signature = (signature or "").strip() or None
        if not outpost_id:
            raise ValueError("outpost_id required")
        if not body:
            raise ValueError("body required")
        if len(body) > MAX_BODY:
            raise ValueError(f"body too long (max {MAX_BODY})")
        if signature and len(signature) > MAX_SIGNATURE:
            raise ValueError(f"signature too long (max {MAX_SIGNATURE})")
        return self.store.queue_outbox(
            outpost_id=outpost_id, body=body, signature=signature, note_id=note_id
        )

    def sync(
        self,
        *,
        outpost_id: str,
        display_name: Optional[str],
        notes: list[Any],
    ) -> dict[str, Any]:
        """Ingest an Outpost's board (dedup by id) and piggyback its
        outbox back in the same round trip — same "the response is the
        delivery confirmation" shape as DispatchService._rpc_sync."""
        if not outpost_id:
            raise ValueError("outpost_id required")
        display_name = (display_name or "").strip()[:MAX_DISPLAY_NAME] or None
        self.store.touch_outpost(outpost_id, display_name=display_name)

        ingested = 0
        for n in notes:
            if not isinstance(n, dict) or not n.get("id") or n.get("body") is None:
                continue
            body = str(n["body"]).strip()[:MAX_BODY]
            if not body:
                continue
            signature = n.get("signature")
            signature = str(signature).strip()[:MAX_SIGNATURE] if signature else None
            _, created = self.store.add_note(
                outpost_id=outpost_id,
                body=body,
                signature=signature,
                note_id=str(n["id"]),
                created_at=n.get("created_at"),
            )
            if created:
                ingested += 1

        pending = self.store.list_outbox(outpost_id)
        for row in pending:
            self.store.clear_outbox(row["id"])

        return {"ingested": ingested, "pending": pending}

    async def handle_rpc(self, envelope: Envelope) -> Envelope:
        # Async (unlike Beacon/Noticeboard's sync handle_rpc) so it works
        # uniformly through both WaylinkGateway's dispatch (which checks
        # iscoroutine) and the /api/waylink/rpc test endpoint's generic
        # fallback (which always awaits the handler) — no internal await
        # is otherwise needed, every store call here is synchronous.
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_BOARD_SYNC:
                notes = payload.get("notes")
                result = self.sync(
                    outpost_id=str(envelope.src or ""),
                    display_name=payload.get("display_name"),
                    notes=notes if isinstance(notes, list) else [],
                )
                return envelope.make_response(
                    op=op,
                    payload={"ok": True, **result},
                    flags=Flags.RESPONSE | Flags.ACK,
                )
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except ValueError as exc:
            return envelope.make_response(op=op, payload={"error": str(exc)}, error=True)
