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

import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Optional

from server.api.db import Database
from server.services.corkboard.constants import OP_OUTPOST_CLAIM
from server.services.profiles.constants import (
    OP_LOGIN,
    OP_LOGIN_NONCE,
    OP_PAIR_REDEEM,
    OP_UNPAIR,
    OP_WHOAMI,
)
from shared.protocol.envelope import Envelope, Flags

if TYPE_CHECKING:
    from server.services.corkboard.store import CorkboardStore
    from server.services.dispatch.service import DispatchService

logger = logging.getLogger("waypost.pairing")

CODE_TTL_SECONDS = 10 * 60
CODE_LENGTH = 6
# A 6-digit code is only safe if it can't be guessed in its 10 minutes:
# redemption needs no sign-in (it's how a device first binds), so wrong
# codes are limited Station-wide — after this many in a minute, every
# redemption waits out the minute (about 35 days to search all codes).
MAX_BAD_CODES_PER_MINUTE = 20
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
        self.identity = None  # IdentityService, set in main.py (Scout login)
        self._nonces: dict[str, tuple[bytes, float]] = {}  # node -> (challenge, expires)
        self._bad_codes: list[float] = []  # times of recent wrong redemptions

    def _learn_route(self, node_id: str, transport_dest: Optional[str]) -> None:
        if not transport_dest or self.transport is None:
            return
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
        now = time.time()
        self._bad_codes = [t for t in self._bad_codes if now - t < 60]
        if len(self._bad_codes) >= MAX_BAD_CODES_PER_MINUTE:
            raise ValueError("too many wrong pairing codes - try again in a minute")
        row = self.db.get_pairing_code(code.strip())
        if not row:
            self._bad_codes.append(now)
            raise ValueError("invalid pairing code")
        if row["used_at"]:
            raise ValueError("pairing code already used")
        if float(row["expires_at"]) < time.time():
            raise ValueError("pairing code expired")
        if not self.db.mark_pairing_code_used(row["code"], used_at=time.time()):
            # Lost a race with another redemption of the same code between
            # the read above and now — the atomic claim is the real guard.
            raise ValueError("pairing code already used")
        binding = self.dispatch.bind_device(
            node_id, row["username"], transport_dest=transport_dest
        )
        # Must happen before handle_rpc returns — see module docstring.
        self._learn_route(node_id, transport_dest)
        return binding

    async def handle_rpc(self, env: Envelope) -> Envelope:
        """Waylink parity for radio-only devices — same single-use code,
        no password ever crosses LoRa (docs/security.md)."""
        if env.op in (OP_WHOAMI, OP_UNPAIR, OP_LOGIN_NONCE, OP_LOGIN):
            self._route_reply_to_unbound(env)
        if env.op == OP_LOGIN_NONCE:
            return self._rpc_login_nonce(env)
        if env.op == OP_LOGIN:
            return self._rpc_login(env)
        if env.op == OP_WHOAMI:
            return self._rpc_whoami(env)
        if env.op == OP_UNPAIR:
            # Idempotent: an already-unbound device gets ok too, so a Scout
            # retrying after a lost reply converges.
            binding = self.dispatch.store.get_binding(env.src)
            if binding:
                self.dispatch.unbind_device(env.src, username=binding["username"])
            return env.make_response(op=OP_UNPAIR, payload={"ok": True})
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

    def _route_reply_to_unbound(self, env: Envelope) -> None:
        """A Reticulum packet doesn't say where it came from: Station can
        only reply to a device whose destination hash it knows, normally from
        its binding. An unbound device (never paired, or unpaired from the
        portal) would never hear "not_paired", so it may include its own
        `transport_dest`. Only honoured when the node has **no binding** — a
        bound device's route always comes from its binding, so nobody can
        redirect another device's traffic by claiming its node id."""
        if self.dispatch.store.get_binding(env.src):
            return
        payload = env.payload if isinstance(env.payload, dict) else {}
        dest = payload.get("transport_dest")
        if not dest:
            return
        try:
            self._learn_route(str(env.src), str(dest))
        except ValueError:
            logger.info("whoami_bad_transport_dest node=%s", env.src)

    # -- Scout login with username + password (2026-10-05) -----------------------
    #
    # The Scout works out the person's identity key from username + password
    # (server/services/identity/keys.py) and signs a one-time challenge with
    # it. The password never crosses the radio, and the challenge can't be
    # used to test password guesses (that needs the key). Station only knows
    # a person's key once it has seen their password — at registration or a
    # portal sign-in — hence "no_identity_yet" for older accounts.

    LOGIN_MAGIC = b"WAYPOST-LOGIN-1\n"
    NONCE_TTL = 120.0

    @classmethod
    def login_bytes(cls, node_id: str, dest: bytes, nonce: bytes) -> bytes:
        return cls.LOGIN_MAGIC + node_id.encode("utf-8") + b"\n" + bytes(dest) + b"\n" + bytes(nonce)

    def _rpc_login_nonce(self, env: Envelope) -> Envelope:
        nonce = secrets.token_bytes(16)
        self._nonces[str(env.src)] = (nonce, time.time() + self.NONCE_TTL)
        return env.make_response(op=OP_LOGIN_NONCE, payload={"nonce": nonce})

    def _rpc_login(self, env: Envelope) -> Envelope:
        from server.services.identity import certs as C

        def err(code: str) -> Envelope:
            return env.make_response(op=OP_LOGIN, payload={"error": code}, error=True)

        p = env.payload if isinstance(env.payload, dict) else {}
        username, dest, sig = str(p.get("u") or ""), p.get("rd"), p.get("sig")
        if not (isinstance(dest, bytes) and len(dest) == 16 and isinstance(sig, bytes) and len(sig) == 64):
            return err("invalid_payload")
        nonce, expires = self._nonces.pop(str(env.src), (b"", 0.0))
        if not nonce or expires < time.time():
            return err("login_expired")
        user = self.db.get_user_by_username(username)
        if not user:
            return err("unknown_user")
        if not user.get("is_admin") and not user.get("approved_at"):
            return err("account pending admin approval")
        known = self.identity.store.key_for(user["username"]) if self.identity else None
        if not known:
            return err("no_identity_yet")
        if not C.verify_signing_key(known[0], sig, self.login_bytes(str(env.src), dest, nonce)):
            return err("wrong_password")
        binding = self.dispatch.bind_device(str(env.src), user["username"], transport_dest=dest.hex())
        self._learn_route(str(env.src), dest.hex())
        return env.make_response(
            op=OP_LOGIN,
            payload={"ok": True, "username": user["username"],
                     "display_name": (user.get("display_name") or user["username"])[:40]},
            flags=Flags.RESPONSE | Flags.ACK,
        )

    def _rpc_whoami(self, env: Envelope) -> Envelope:
        binding = self.dispatch.store.get_binding(env.src)
        if not binding:
            return env.make_response(
                op=OP_WHOAMI, payload={"error": "not_paired"}, error=True
            )
        user = self.db.get_user_by_username(binding["username"]) or {}
        return env.make_response(
            op=OP_WHOAMI,
            payload={
                "username": binding["username"],
                "display_name": (user.get("display_name") or binding["username"])[:40],
            },
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
        if not self.db.mark_pairing_code_used(row["code"], used_at=time.time()):
            # Lost a race with another redemption of the same code between
            # the read above and now — the atomic claim is the real guard.
            raise ValueError("pairing code already used")
        # Two un-relabeled boards (both defaulting to the same firmware
        # WAYPOST_OUTPOST_ID) would otherwise silently merge here — same
        # node_id, different physical device, different transport_dest.
        # Station can't safely tell that apart from a legitimate re-claim
        # of the same board after a real identity reset (both look like
        # "same id, new hash"), so this doesn't block it — but it must not
        # stay invisible either.
        existing = self.corkboard_store.get_outpost(node_id)
        replaced_existing_claim = bool(
            existing
            and existing.get("transport_dest")
            and existing["transport_dest"].lower() != transport_dest.lower()
        )
        if replaced_existing_claim:
            logger.warning(
                "outpost_claim node_id=%s replaced a different existing "
                "transport_dest — check for a WAYPOST_OUTPOST_ID collision "
                "unless this is a known re-claim after a board reset",
                node_id,
            )
        # Must happen before handle_outpost_claim returns — see module docstring.
        self._learn_route(node_id, transport_dest)
        outpost = self.corkboard_store.touch_outpost(
            node_id, display_name=display_name, transport_dest=transport_dest
        )
        result: dict[str, Any] = {"node_id": node_id, "outpost": outpost}
        if replaced_existing_claim:
            result["replaced_existing_claim"] = True
        return result

    def auto_claim_outpost(
        self,
        *,
        node_id: str,
        transport_dest: str,
        display_name: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Claim an Outpost heard over a genuine Reticulum announce, no
        pairing code involved — see server/transports/reticulum.py's
        announce handler and docs/security.md's "auto-claim" section for
        why this is a different (not weaker) proof than the code-based
        path: the destination hash here comes from Reticulum's own signed
        announce, not a self-reported payload field, and the Outpost only
        advertises itself this way when its own physical-button-toggled
        auto_claim_enabled flag is on. Idempotent — a no-op once claimed,
        since announces repeat periodically and this fires on each one.
        """
        node_id = (node_id or "").strip()
        if not node_id or self.corkboard_store is None:
            return None
        try:
            transport_dest = _normalize_transport_dest(transport_dest)
        except ValueError:
            return None
        if self.corkboard_store.is_claimed(node_id):
            return None
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
