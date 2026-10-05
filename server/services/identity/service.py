"""Identity service: issues and serves certificates over Waylink (PROFILE
``CERT_*`` ops, docs/protocol.md) so devices can verify people offline.

Station's part is issuing, revoking and recovery — never a step that an
ordinary login or message waits on (docs/network-model.md §7).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from server.services.identity import certs as C
from server.services.identity.store import IdentityStore
from server.services.profiles.constants import (
    OP_CERT_DEV,
    OP_CERT_GET,
    OP_CERT_ISSUE,
    OP_CERT_REVOKED,
    OP_CERT_ROOT,
)
from shared.protocol.envelope import Envelope
from shared.protocol.radio import fit_list_reply

CERT_LIFETIME_SEC = 30 * 24 * 3600
RENEW_BEFORE_SEC = 7 * 24 * 3600  # serve a fresh certificate once this close to expiry

WAYLINK_APP = "waypost"
WAYLINK_ASPECTS = ("waylink",)


def waylink_dest_hex(public_key: bytes) -> tuple[str, bytes]:
    """(destination hash hex, identity hash) for a device's Reticulum public
    key, as every Waypost node computes its own ``waypost.waylink`` address."""
    import RNS

    ident = RNS.Identity(create_keys=False)
    ident.load_public_key(bytes(public_key))
    dest = RNS.Destination.hash(ident, WAYLINK_APP, *WAYLINK_ASPECTS)
    return dest.hex(), bytes(ident.hash)


def reticulum_signature_ok(public_key: bytes, signature: bytes, message: bytes) -> bool:
    import RNS

    try:
        ident = RNS.Identity(create_keys=False)
        ident.load_public_key(bytes(public_key))
        return bool(ident.validate(bytes(signature), message))
    except Exception:
        return False


class IdentityService:
    def __init__(
        self,
        store: IdentityStore,
        key: C.CommunityKey,
        *,
        get_binding: Callable[[str], Optional[dict[str, Any]]],
        get_user: Callable[[str], Optional[dict[str, Any]]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.key = key
        self._get_binding = get_binding
        self._get_user = get_user
        self._clock = clock

    def now(self) -> int:
        return int(self._clock())

    # -- issuing --------------------------------------------------------------

    def identity_cert(self, username: str) -> Optional[dict[str, Any]]:
        user = self._get_user(username)
        if not user:
            return None
        username = user["username"]
        name = C.clip_utf8(str(user.get("display_name") or username), C.MAX_DISPLAY_NAME)
        now = self.now()
        row = self.store.latest_identity(username)
        if not row or row["expires"] - now < RENEW_BEFORE_SEC or row["display_name"] != name:
            row = self.store.add_identity(
                username=username,
                identity_id=self.store.identity_id(username),
                display_name=name,
                issued=now,
                expires=now + CERT_LIFETIME_SEC,
            )
        return self._wire(row)

    def issue_device_cert(
        self, *, node_id: str, username: str, signing_key: bytes, device_hash: bytes
    ) -> dict[str, Any]:
        now = self.now()
        for row in self.store.certs_for_node(node_id):
            same = bytes(row["signing_key"]) == bytes(signing_key) and str(row["username"]).lower() == username.lower()
            if same and row["expires"] - now >= RENEW_BEFORE_SEC:
                return self._wire(row)
            if not same:
                # A new key (re-paired, PIN reset) or a different person on
                # this device: the old certificate must stop being believed.
                self.store.revoke(row["serial"], now)
        row = self.store.add_device(
            username=username,
            identity_id=self.store.identity_id(username),
            node_id=node_id,
            signing_key=bytes(signing_key),
            device_hash=bytes(device_hash),
            issued=now,
            expires=now + CERT_LIFETIME_SEC,
        )
        return self._wire(row)

    def sweep(self) -> int:
        """Revoke device certificates whose device is no longer paired to
        that person (unpaired, revoked from the portal, re-paired to someone
        else). Lazy: runs before anything that serves certificates."""
        now = self.now()
        n = 0
        for row in self.store.live_device_certs(now):
            binding = self._get_binding(row["node_id"])
            if not binding or str(binding["username"]).lower() != str(row["username"]).lower():
                if self.store.revoke(row["serial"], now):
                    n += 1
        return n

    def device_certs(self, username: str) -> list[dict[str, Any]]:
        self.sweep()
        return [self._wire(r) for r in self.store.device_certs(username, self.now())]

    def revocations(self) -> list[dict[str, Any]]:
        self.sweep()
        return [self._wire(r) for r in self.store.revocations(self.now())]

    def _wire(self, row: dict[str, Any]) -> dict[str, Any]:
        kind = row["kind"]
        if kind == C.KIND_IDENTITY:
            cert = {"k": kind, "n": row["serial"], "i": bytes(row["identity_id"]), "u": row["username"],
                    "dn": row["display_name"], "t": row["issued"], "x": row["expires"]}
        elif kind == C.KIND_DEVICE:
            cert = {"k": kind, "n": row["serial"], "i": bytes(row["identity_id"]), "u": row["username"],
                    "p": bytes(row["signing_key"]), "d": bytes(row["device_hash"]),
                    "t": row["issued"], "x": row["expires"]}
        else:
            cert = {"k": kind, "n": row["serial"], "r": row["revokes"], "t": row["issued"]}
        return self.key.sign(cert)

    # -- Waylink --------------------------------------------------------------

    async def handle_rpc(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}

        def err(code: str) -> Envelope:
            return env.make_response(op=env.op, payload={"error": code}, error=True)

        # The community public key is public: anyone may ask (a device
        # pins it at pairing and refuses a different one later).
        if env.op == OP_CERT_ROOT:
            return env.make_response(op=env.op, payload={"pk": self.key.public_bytes})

        binding = self._get_binding(env.src)
        if not binding:
            return err("unauthorized_device")
        me = str(binding["username"])

        if env.op == OP_CERT_ISSUE:
            return self._rpc_issue(env, payload, binding, err)

        if env.op == OP_CERT_GET:
            who = str(payload.get("u") or me)
            cert = self.identity_cert(who)
            if not cert:
                return err("unknown_user")
            return env.make_response(
                op=env.op, payload={"cert": cert, "devs": len(self.device_certs(who))}
            )

        if env.op == OP_CERT_DEV:
            who = str(payload.get("u") or me)
            index = max(0, int(payload.get("i") or 0))
            devs = self.device_certs(who)
            if index >= len(devs):
                return env.make_response(op=env.op, payload={"cert": None, "more": False})
            return env.make_response(
                op=env.op, payload={"cert": devs[index], "more": index + 1 < len(devs)}
            )

        if env.op == OP_CERT_REVOKED:
            offset = max(0, int(payload.get("offset") or 0))
            items = self.revocations()[offset:]
            reply, _ = fit_list_reply(
                lambda part, more: env.make_response(
                    op=env.op, payload={"revs": part, "offset": offset, "more": more}
                ),
                items,
            )
            return reply

        return err(f"unknown_op:{env.op}")

    def _rpc_issue(self, env: Envelope, payload: dict, binding: dict, err) -> Envelope:
        pk, spk, sig = payload.get("pk"), payload.get("spk"), payload.get("sig")
        if not (isinstance(pk, bytes) and len(pk) == 64 and isinstance(spk, bytes) and len(spk) == 32
                and isinstance(sig, bytes) and len(sig) == 64):
            return err("invalid_payload")
        # The request must come from the device that was paired: its
        # Reticulum key must hash to the paired address, and it must have
        # signed this request (env.src alone is only a claim).
        dest_hex, device_hash = waylink_dest_hex(pk)
        if not binding.get("transport_dest") or dest_hex != str(binding["transport_dest"]).lower():
            return err("device_key_mismatch")
        if not reticulum_signature_ok(pk, sig, C.issue_request_bytes(env.src, spk)):
            return err("bad_signature")
        cert = self.issue_device_cert(
            node_id=env.src, username=str(binding["username"]), signing_key=spk, device_hash=device_hash
        )
        return env.make_response(op=env.op, payload={"cert": cert})
