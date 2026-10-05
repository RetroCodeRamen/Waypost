"""Identity service: records each person's identity key (derived from
username + password, keys.py) and vouches for it with certificates served
over Waylink (PROFILE ``CERT_*`` ops, docs/protocol.md), so any device can
check who wrote something with no Station in reach.

Station's part is recording keys, vouching, revoking — never a step that an
ordinary login or message waits on (docs/network-model.md §7).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from server.services.identity import certs as C
from server.services.identity import keys as K
from server.services.identity import objects as O
from server.services.identity.store import IdentityStore
from server.services.profiles.constants import OP_CERT_GET, OP_CERT_REVOKED, OP_CERT_ROOT
from shared.protocol.envelope import Envelope
from shared.protocol.radio import fit_list_reply

CERT_LIFETIME_SEC = 30 * 24 * 3600
RENEW_BEFORE_SEC = 7 * 24 * 3600  # serve a fresh certificate once this close to expiry


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

    # -- keys -------------------------------------------------------------------

    def record_password(self, username: str, password: str) -> bytes:
        """Called wherever Station sees a password (registration, portal
        sign-in, password change): works out the person's identity key and
        records it. A different password than before means a new identity —
        the old one's certificates are revoked. Returns the public key."""
        public = K.public_key(username, password)
        self.record_key(username, public)
        return public

    def record_key(self, username: str, public: bytes) -> None:
        old = self.store.set_key(username, public, K.identity_id(public))
        if old is not None:
            self.store.revoke_identity(old, self.now())
        self.identity_cert(username)  # vouch for it straight away

    # -- issuing --------------------------------------------------------------

    def identity_cert(self, username: str) -> Optional[dict[str, Any]]:
        """The person's certificate, or None when Station doesn't know their
        key yet (they haven't signed in since keys came in)."""
        user = self._get_user(username)
        if not user:
            return None
        username = user["username"]
        known = self.store.key_for(username)
        if not known:
            return None
        public, ident = known
        name = C.clip_utf8(str(user.get("display_name") or username), C.MAX_DISPLAY_NAME)
        now = self.now()
        row = self.store.latest_identity(username)
        if (not row or row["expires"] - now < RENEW_BEFORE_SEC or row["display_name"] != name
                or bytes(row["public_key"]) != public):
            row = self.store.add_identity(username=username, identity_id=ident, display_name=name,
                                          public_key=public, issued=now, expires=now + CERT_LIFETIME_SEC)
        return self._wire(row)

    def cert_for_id(self, identity_id: bytes) -> Optional[dict[str, Any]]:
        row = self.store.by_identity_id(identity_id)
        if not row or row["revoked_at"] is not None:
            return None
        return self.identity_cert(str(row["username"]))

    def revocations(self) -> list[dict[str, Any]]:
        return [self._wire(r) for r in self.store.revocations(self.now())]

    def _wire(self, row: dict[str, Any]) -> dict[str, Any]:
        if row["kind"] == C.KIND_IDENTITY:
            cert = {"k": "id", "n": row["serial"], "i": bytes(row["identity_id"]), "u": row["username"],
                    "dn": row["display_name"], "p": bytes(row["public_key"]),
                    "t": row["issued"], "x": row["expires"]}
        else:
            cert = {"k": "rev", "n": row["serial"], "r": row["revokes"], "t": row["issued"]}
        return self.key.sign(cert)

    # -- checking ------------------------------------------------------------------

    def verify_object(self, obj: dict[str, Any], signature: bytes) -> tuple[Optional[str], str]:
        """Checks an object signed with a person's identity key. ``obj`` has
        every field but ``u`` — the author comes from the identity id ``a``.
        Returns (author username, "") or (None, error code)."""
        ident = obj.get("a")
        if not isinstance(ident, (bytes, bytearray)) or len(ident) != 16:
            return None, "invalid_payload"
        row = self.store.by_identity_id(bytes(ident))
        if not row:
            return None, "unknown_identity"
        if row["revoked_at"] is not None:
            return None, "identity_revoked"
        signed = dict(obj, u=str(row["username"]))
        try:
            message = O.canonical_bytes(signed)
        except C.CertError:
            return None, "invalid_payload"
        if not isinstance(signature, (bytes, bytearray)) or len(signature) != 64:
            return None, "invalid_payload"
        if not C.verify_signing_key(bytes(row["public_key"]), bytes(signature), message):
            return None, "bad_signature"
        return str(row["username"]), ""

    def owner_of(self, identity_id: bytes) -> Optional[str]:
        """Whose identity id this is — replaced (revoked) keys included, so
        a message signed with one is refused as revoked, not as unknown.
        Whether it's still good is verify_object's call."""
        return self.store.owner_of(bytes(identity_id))

    # -- Waylink --------------------------------------------------------------

    async def handle_rpc(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}

        def err(code: str) -> Envelope:
            return env.make_response(op=env.op, payload={"error": code}, error=True)

        # The community public key is public: anyone may ask (a device
        # pins it the first time and refuses a different one later).
        if env.op == OP_CERT_ROOT:
            return env.make_response(op=env.op, payload={"pk": self.key.public_bytes})

        binding = self._get_binding(env.src)
        if not binding:
            return err("unauthorized_device")

        if env.op == OP_CERT_GET:
            ident = payload.get("i")
            if isinstance(ident, bytes):
                cert = self.cert_for_id(ident)
                if not cert:
                    return err("unknown_identity")
            else:
                who = str(payload.get("u") or binding["username"])
                if not self._get_user(who):
                    return err("unknown_user")
                cert = self.identity_cert(who)
                if not cert:
                    return err("no_identity_yet")
            return env.make_response(op=env.op, payload={"cert": cert})

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
