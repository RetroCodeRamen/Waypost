"""Pairing codes — link a device node_id to an account without a password.

Redeeming a code calls the existing DispatchService.bind_device, so a
Pocket that only has LoRa (no Wi-Fi/HTTP session yet) can still bind
without ever sending a password over the air — see docs/security.md.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any, Optional

from server.api.db import Database
from server.services.profiles.constants import OP_PAIR_REDEEM
from shared.protocol.envelope import Envelope, Flags

if TYPE_CHECKING:
    from server.services.dispatch.service import DispatchService

CODE_TTL_SECONDS = 10 * 60
CODE_LENGTH = 6
_MAX_CREATE_ATTEMPTS = 5
_DIGITS = "0123456789"


class PairingService:
    def __init__(self, db: Database, dispatch: "DispatchService") -> None:
        self.db = db
        self.dispatch = dispatch

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
        return self.dispatch.bind_device(
            node_id, row["username"], transport_dest=transport_dest
        )

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
            binding = self.redeem_code(code=str(payload["code"]), node_id=node_id)
        except ValueError as exc:
            return env.make_response(
                op=OP_PAIR_REDEEM, payload={"error": str(exc)}, error=True
            )
        return env.make_response(
            op=OP_PAIR_REDEEM,
            payload={"ok": True, **binding},
            flags=Flags.RESPONSE | Flags.ACK,
        )
