"""Pairing codes — link a device node_id to an account without a password,
or (same codes, different redemption) let a Station user claim an Outpost.

Redeeming a code for a Pocket calls the existing DispatchService.bind_device,
so a device that only has LoRa (no Wi-Fi/HTTP session yet) can still bind
without ever sending a password over the air — see docs/security.md.
Claiming an Outpost is the same trust model (a human-provided code proves
intent) but registers a Corkboard outpost instead of a Dispatch device —
an Outpost has no username, so bind_device doesn't fit.

Either redemption needs to teach the live transport how to reach the
claimant *before* the reply is sent (WaylinkGateway resolves the reply
destination only after the handler returns — see server/gateway/waylink.py
send_envelope) — otherwise the very first response a freshly-pairing
device is owed can't be routed back to it. `self.transport` is assigned
after construction (see server/api/main.py) since the Transport doesn't
exist yet when PairingService is built.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any, Optional

from server.api.db import Database
from server.services.corkboard.constants import OP_OUTPOST_CLAIM
from server.services.profiles.constants import OP_PAIR_REDEEM
from shared.protocol.envelope import Envelope, Flags

if TYPE_CHECKING:
    from server.services.corkboard.store import CorkboardStore
    from server.services.dispatch.service import DispatchService

CODE_TTL_SECONDS = 10 * 60
CODE_LENGTH = 6
_MAX_CREATE_ATTEMPTS = 5
_DIGITS = "0123456789"


def _normalize_transport_dest(transport_dest: str) -> str:
    raw = transport_dest.strip().lower().replace(":", "")
    if len(raw) != 32 or any(c not in "0123456789abcdef" for c in raw):
        raise ValueError(f"transport_dest must be 32 hex chars, got {transport_dest!r}")
    return raw


class PairingService:
    def __init__(
        self,
        db: Database,
        dispatch: "DispatchService",
        corkboard_store: Optional["CorkboardStore"] = None,
    ) -> None:
        self.db = db
        self.dispatch = dispatch
        self.corkboard_store = corkboard_store
        self.transport = None  # set once Transport exists, see main.py

    def _learn_route(self, node_id: str, transport_dest: Optional[str]) -> None:
        if not transport_dest or self.transport is None:
            return
        if hasattr(self.transport, "learn_route"):
            self.transport.learn_route(node_id, transport_dest)

    def create_code(self, username: str) -> dict[str, Any]:
        now = time.time()
        expires_at = now + CODE_TTL_SECONDS
        for _ in range(_MAX_CREATE_ATTEMPTS):
            code = "".join(secrets.choice(_DIGITS) for _ in range(CODE_LENGTH))
            if self.db.get_pairing_code(code):
                continue
            self.db.create_pairing_code(
                code=code, username=username, created_at=now, expires_at=expires_at
            )
            return {"code": code, "expires_at": expires_at}
        raise RuntimeError("could not generate a unique pairing code")

    def redeem_code(
        self, *, code: str, node_id: str, transport_dest: Optional[str] = None
    ) -> dict[str, Any]:
        row = self.db.get_pairing_code(code.strip())
        if not row:
            raise ValueError("invalid pairing code")
        if row["used_at"]:
            raise ValueError("pairing code already used")
        if float(row["expires_at"]) < time.time():
            raise ValueError("pairing code expired")
        self.db.mark_pairing_code_used(row["code"], used_at=time.time())
        binding = self.dispatch.bind_device(
            node_id, row["username"], transport_dest=transport_dest
        )
        # Must happen before handle_rpc returns — see module docstring.
        self._learn_route(node_id, transport_dest)
        return binding

    async def handle_rpc(self, env: Envelope) -> Envelope:
        """Waylink parity for radio-only devices — same single-use code,
        no password ever crosses LoRa (docs/security.md)."""
        if env.op != OP_PAIR_REDEEM:
            return env.make_response(
                op=env.op,
                payload={"error": "unknown_operation", "op": env.op},
                error=True,
            )
        payload = env.payload or {}
        if not isinstance(payload, dict) or not payload.get("code"):
            return env.make_response(
                op=OP_PAIR_REDEEM, payload={"error": "code_required"}, error=True
            )
        node_id = str(payload.get("node_id") or env.src)
        try:
            binding = self.redeem_code(
                code=str(payload["code"]),
                node_id=node_id,
                transport_dest=payload.get("transport_dest"),
            )
        except ValueError as exc:
            return env.make_response(
                op=OP_PAIR_REDEEM, payload={"error": str(exc)}, error=True
            )
        return env.make_response(
            op=OP_PAIR_REDEEM,
            payload={"ok": True, **binding},
            flags=Flags.RESPONSE | Flags.ACK,
        )

    def redeem_outpost_code(
        self,
        *,
        code: str,
        node_id: str,
        transport_dest: str,
        display_name: Optional[str] = None,
    ) -> dict[str, Any]:
        row = self.db.get_pairing_code(code.strip())
        if not row:
            raise ValueError("invalid pairing code")
        if row["used_at"]:
            raise ValueError("pairing code already used")
        if float(row["expires_at"]) < time.time():
            raise ValueError("pairing code expired")
        node_id = node_id.strip()
        if not node_id:
            raise ValueError("node_id required")
        transport_dest = _normalize_transport_dest(transport_dest)
        if self.corkboard_store is None:
            raise ValueError("outpost claiming is not available")
        self.db.mark_pairing_code_used(row["code"], used_at=time.time())
        # Must happen before handle_outpost_claim returns — see module docstring.
        self._learn_route(node_id, transport_dest)
        outpost = self.corkboard_store.touch_outpost(
            node_id, display_name=display_name, transport_dest=transport_dest
        )
        return {"node_id": node_id, "outpost": outpost}

    async def handle_outpost_claim(self, env: Envelope) -> Envelope:
        """An Outpost redeeming a Station-generated pairing code to
        register itself and teach Station how to reach it — same codes
        `create_code`/`handle_rpc` already generate for Pocket devices,
        different redemption target (a Corkboard outpost has no
        username, so bind_device doesn't fit)."""
        if env.op != OP_OUTPOST_CLAIM:
            return env.make_response(
                op=env.op,
                payload={"error": "unknown_operation", "op": env.op},
                error=True,
            )
        payload = env.payload or {}
        if (
            not isinstance(payload, dict)
            or not payload.get("code")
            or not payload.get("transport_dest")
        ):
            return env.make_response(
                op=OP_OUTPOST_CLAIM,
                payload={"error": "code_and_transport_dest_required"},
                error=True,
            )
        node_id = str(payload.get("node_id") or env.src)
        try:
            result = self.redeem_outpost_code(
                code=str(payload["code"]),
                node_id=node_id,
                transport_dest=str(payload["transport_dest"]),
                display_name=payload.get("display_name"),
            )
        except ValueError as exc:
            return env.make_response(
                op=OP_OUTPOST_CLAIM, payload={"error": str(exc)}, error=True
            )
        return env.make_response(
            op=OP_OUTPOST_CLAIM,
            payload={"ok": True, **result},
            flags=Flags.RESPONSE | Flags.ACK,
        )
