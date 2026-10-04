"""Beacon service — emergency / high-priority community alerts."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from server.services.beacon.constants import (
    MAX_BODY,
    MAX_TITLE,
    OP_BEACON_ALERT,
    OP_BEACON_CLEAR,
    OP_BEACON_GET,
    OP_BEACON_LIST,
    OP_BEACON_PUSH,
    OP_BEACON_SYNC,
    PUSH_COOLDOWN_SEC,
)
from server.services.beacon.store import BeaconStore
from shared.protocol.envelope import SVC_BEACON, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU, chunk_utf8, fit_list_reply

logger = logging.getLogger("waypost.beacon")

ALLOWED_SEVERITY = {"emergency", "urgent", "advisory"}


class BeaconService:
    def __init__(
        self,
        store: BeaconStore,
        *,
        get_binding: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
        is_claimed_outpost: Optional[Callable[[str], bool]] = None,
        list_radio_nodes: Optional[Callable[[], list[str]]] = None,
    ) -> None:
        self.store = store
        # Every paired radio device (Scouts) is told the moment a Beacon is
        # raised or cleared — an emergency can't wait for someone to look.
        self._list_radio_nodes = list_radio_nodes or (lambda: [])
        self._radio_push: Optional[Callable[[Envelope], None]] = None
        # Same injected cross-service lookup as PostboxService/NoticeboardService
        # (avoids importing DispatchStore directly). Without it, BEACON_PUSH/
        # CLEAR over Waylink trusted whatever the packet's own payload
        # claimed — for an emergency-alert system, that meant anyone with a
        # working radio could push (or silence) an alert as anyone.
        self._get_binding = get_binding or (lambda _node_id: None)
        # Same shape, for BEACON_SYNC: is envelope.src a Corkboard-claimed
        # Outpost (went through OUTPOST_CLAIM, not just "sent a packet once")?
        self._is_claimed_outpost = is_claimed_outpost or (lambda _node_id: False)

    def set_radio_push(self, callback: Callable[[Envelope], None]) -> None:
        self._radio_push = callback

    @staticmethod
    def compact(beacon: dict[str, Any], body_limit: int = 160) -> dict[str, Any]:
        """Radio form of a Beacon (keys kept short; body cut to fit)."""
        body = str(beacon.get("body") or "")
        piece, total = chunk_utf8(body, 0, body_limit)
        return {
            "id": beacon["id"],
            "t": str(beacon.get("title") or "")[:60],
            "sev": beacon.get("severity") or "emergency",
            "b": piece if len(piece.encode("utf-8")) >= total else piece + "…",
            "a": str(beacon.get("author") or "")[:32],
            "ts": int(beacon.get("created_at") or 0),
            "on": bool(beacon.get("active")),
        }

    def _notify(self, beacon: Optional[dict[str, Any]]) -> None:
        if not beacon or self._radio_push is None:
            return
        for node_id in self._list_radio_nodes():
            env = self._fit_alert(node_id, beacon)
            try:
                self._radio_push(env)
            except Exception:
                logger.exception("beacon_alert_push_failed node=%s", node_id)
        logger.info(
            "beacon_alert id=%s active=%s nodes=%d",
            beacon["id"], bool(beacon.get("active")), len(self._list_radio_nodes()),
        )

    @staticmethod
    def _shrink_to_fit(build: Callable[[int], Envelope]) -> Envelope:
        """build(body_limit) -> Envelope; cut the body until it fits one
        packet (shared/protocol/radio.py)."""
        limit = 160
        env = build(limit)
        while len(encode_cbor(env)) > RADIO_MDU and limit > 8:
            limit = max(8, limit - (len(encode_cbor(env)) - RADIO_MDU) - 2)
            env = build(limit)
        return env

    def _fit_alert(self, node_id: str, beacon: dict[str, Any]) -> Envelope:
        return self._shrink_to_fit(
            lambda limit: Envelope(
                src="station", dst=node_id, svc=SVC_BEACON, op=OP_BEACON_ALERT,
                flags=int(Flags.REQUEST), payload=self.compact(beacon, limit),
            )
        )

    def _bound_username(self, node_id: str) -> Optional[str]:
        binding = self._get_binding(node_id)
        return str(binding["username"]) if binding else None

    def push(
        self,
        *,
        author: str,
        title: str,
        body: str,
        severity: str = "emergency",
        beacon_id: Optional[str] = None,
        mid: Optional[str] = None,
        bypass_cooldown: bool = False,
    ) -> dict[str, Any]:
        author = author.strip()
        title = (title or "").strip()
        body = (body or "").strip()
        severity = (severity or "emergency").strip().lower()
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
        if severity not in ALLOWED_SEVERITY:
            raise ValueError("severity must be emergency, urgent, or advisory")
        if not bypass_cooldown:
            last = self.store.last_push_at(author)
            if last is not None and (time.time() - last) < PUSH_COOLDOWN_SEC:
                raise ValueError(
                    f"rate limited — wait {PUSH_COOLDOWN_SEC}s between Beacon pushes"
                )
        beacon = self.store.push(
            author=author,
            title=title,
            body=body,
            severity=severity,
            beacon_id=beacon_id,
            mid=mid,
        )
        self._notify(beacon)
        return beacon

    def get_active(self) -> Optional[dict[str, Any]]:
        return self.store.get_active()

    def get(self, beacon_id: str) -> Optional[dict[str, Any]]:
        return self.store.get(beacon_id)

    def list_beacons(self, *, limit: int = 20, active_only: bool = False) -> list[dict[str, Any]]:
        return self.store.list_beacons(limit=limit, active_only=active_only)

    def clear(self, beacon_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        cleared = self.store.clear(beacon_id)
        self._notify(cleared)
        return cleared

    def sync(
        self,
        *,
        outpost_id: str,
        pending: list[Any],
    ) -> dict[str, Any]:
        """Ingest a claimed Outpost's queued push/clear events and return the
        current active beacon — same round-trip shape as Corkboard sync.

        Outposts are walk-up, no-account devices (like Corkboard), so there's
        no real Station identity to bind a push to the way BEACON_PUSH does
        for a paired Pocket. But Beacon is an emergency-alert system, not a
        noteboard — a free-text `author` field would let anyone relaying
        through *any* self-declared node_id impersonate a real account (e.g.
        "aj says evacuate now"). So: (1) the source must be a Corkboard-
        *claimed* Outpost (went through OUTPOST_CLAIM, not just "sent a
        packet claiming this node_id once"), and (2) the pushed beacon's
        author is always attributed to that outpost, never the event's own
        free-text claim — whoever physically reported it can say who they
        are in the body text, but they can't borrow someone else's name as
        the author of record. Cooldown is not bypassed, for the same reason
        it isn't for BEACON_PUSH.
        """
        if not self._is_claimed_outpost(outpost_id):
            return {"error": "unauthorized_outpost", "ingested": 0, "active": self.get_active()}
        ingested = 0
        for ev in pending:
            if not isinstance(ev, dict):
                continue
            op = str(ev.get("op") or "")
            mid = ev.get("mid")
            if op == "push":
                try:
                    self.push(
                        author=f"outpost:{outpost_id}",
                        title=str(ev.get("title") or ""),
                        body=str(ev.get("body") or ""),
                        severity=str(ev.get("severity") or "emergency"),
                        beacon_id=ev.get("id"),
                        mid=str(mid) if mid else None,
                    )
                    ingested += 1
                except ValueError:
                    continue
            elif op == "clear":
                self.clear(ev.get("id"))
                ingested += 1
        return {"ingested": ingested, "active": self.get_active()}

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_BEACON_GET:
                active = self.get_active()
                if payload.get("compact"):  # radio-sized, for Scouts
                    if not active:
                        return envelope.make_response(op=op, payload={"beacon": None})
                    return self._shrink_to_fit(
                        lambda limit: envelope.make_response(
                            op=op, payload={"beacon": self.compact(active, limit)}
                        )
                    )
                return envelope.make_response(op=op, payload={"beacon": active})
            if op == OP_BEACON_LIST and payload.get("compact"):
                items = [
                    {"id": b["id"], "t": str(b.get("title") or "")[:40], "sev": b.get("severity"),
                     "ts": int(b.get("created_at") or 0), "on": bool(b.get("active"))}
                    for b in self.list_beacons(limit=20)
                ]
                reply, _ = fit_list_reply(
                    lambda part, more: envelope.make_response(op=op, payload={"beacons": part, "more": more}),
                    items,
                )
                return reply
            if op == OP_BEACON_LIST:
                beacons = self.list_beacons(
                    limit=int(payload.get("limit") or 20),
                    active_only=bool(payload.get("active_only", False)),
                )
                return envelope.make_response(op=op, payload={"beacons": beacons})
            if op == OP_BEACON_PUSH:
                author = self._bound_username(envelope.src)
                if not author:
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                beacon = self.push(
                    author=author,
                    title=str(payload.get("title") or ""),
                    body=str(payload.get("body") or ""),
                    severity=str(payload.get("severity") or "emergency"),
                    beacon_id=payload.get("id"),
                    mid=envelope.mid or payload.get("mid"),
                )
                return envelope.make_response(op=op, payload={"beacon": beacon})
            if op == OP_BEACON_CLEAR:
                if not self._bound_username(envelope.src):
                    return envelope.make_response(
                        op=op, payload={"error": "unauthorized_device"}, error=True
                    )
                cleared = self.clear(payload.get("id"))
                return envelope.make_response(op=op, payload={"beacon": cleared})
            if op == OP_BEACON_SYNC:
                pending = payload.get("pending")
                result = self.sync(
                    outpost_id=str(envelope.src or ""),
                    pending=pending if isinstance(pending, list) else [],
                )
                if result.get("error"):
                    return envelope.make_response(op=op, payload=result, error=True)
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
