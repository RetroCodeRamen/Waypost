"""Beacon service — emergency / high-priority community alerts."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from server.services.beacon.constants import (
    MAX_BODY,
    MAX_TITLE,
    OP_BEACON_CLEAR,
    OP_BEACON_GET,
    OP_BEACON_LIST,
    OP_BEACON_PUSH,
    PUSH_COOLDOWN_SEC,
)
from server.services.beacon.store import BeaconStore
from shared.protocol.envelope import Envelope, Flags

ALLOWED_SEVERITY = {"emergency", "urgent", "advisory"}


class BeaconService:
    def __init__(
        self,
        store: BeaconStore,
        *,
        get_binding: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    ) -> None:
        self.store = store
        # Same injected cross-service lookup as PostboxService/NoticeboardService
        # (avoids importing DispatchStore directly). Without it, BEACON_PUSH/
        # CLEAR over Waylink trusted whatever the packet's own payload
        # claimed — for an emergency-alert system, that meant anyone with a
        # working radio could push (or silence) an alert as anyone.
        self._get_binding = get_binding or (lambda _node_id: None)

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
        return self.store.push(
            author=author,
            title=title,
            body=body,
            severity=severity,
            beacon_id=beacon_id,
            mid=mid,
        )

    def get_active(self) -> Optional[dict[str, Any]]:
        return self.store.get_active()

    def get(self, beacon_id: str) -> Optional[dict[str, Any]]:
        return self.store.get(beacon_id)

    def list_beacons(self, *, limit: int = 20, active_only: bool = False) -> list[dict[str, Any]]:
        return self.store.list_beacons(limit=limit, active_only=active_only)

    def clear(self, beacon_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        return self.store.clear(beacon_id)

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        try:
            if op == OP_BEACON_GET:
                active = self.get_active()
                return envelope.make_response(op=op, payload={"beacon": active})
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
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except ValueError as exc:
            return envelope.make_response(op=op, payload={"error": str(exc)}, error=True)
