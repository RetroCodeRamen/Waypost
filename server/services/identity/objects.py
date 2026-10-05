"""Signed objects (roadmap D3, docs/network-model.md §3).

An object is signed with its author's **identity key** (derived from
username + password, keys.py; vouched for by an ``id`` certificate). Anyone holding the
certificates can check who wrote it — Station, an Outpost, another Scout —
whoever carried it. Relays can read what they carry but can't alter or
forge it.

Signed bytes follow the certificate convention (certs.py):

    b"WAYPOST-OBJ-1\\n" + name:len:value for each field in the kind's order

First kind: ``dispatch.msg``

    k  "dispatch.msg"
    o  object id, 16 random bytes (also the message id: o.hex())
    u  author's username (from their identity certificate)
    a  author's identity id (SHA-256 of their identity key, first 16 bytes)
    v  conversation id (dm:<a>:<b> for direct messages, room:<slug>)
    b  body text
    t  created, seconds (the author device's clock; informative)

Second kind: ``dispatch.rcpt`` — a delivery receipt (2026-10-05). The
recipient's device signs it when a message lands there; it travels by peer
sync like a message, and "delivered" is derived from it (network-model.md §3).

    k  "dispatch.rcpt"
    o  receipt id: receipt_oid(m, u) — the same for every device of the same
       person, so two copies of a receipt are one receipt
    u  the recipient (the receipt's author)
    a  the recipient's identity id
    v  the message's conversation id
    m  the message's object id (16 bytes)
    t  when it arrived, seconds (the recipient device's clock; informative)
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from server.services.identity.certs import CertError

MAGIC = b"WAYPOST-OBJ-1\n"
KIND_DISPATCH_MSG = "dispatch.msg"
KIND_DISPATCH_RCPT = "dispatch.rcpt"

FIELDS: dict[str, tuple[str, ...]] = {
    KIND_DISPATCH_MSG: ("k", "o", "u", "a", "v", "b", "t"),
    KIND_DISPATCH_RCPT: ("k", "o", "u", "a", "v", "m", "t"),
}
INT_FIELDS = {"t"}
BYTES_FIELDS = {"o": 16, "a": 16, "m": 16}
RCPT_MAGIC = b"WAYPOST-RCPT-1\n"


def new_oid() -> bytes:
    return os.urandom(16)


def receipt_oid(message_oid: bytes, recipient: str) -> bytes:
    """A receipt's id: SHA-256(magic + message id + lower(recipient))[:16]."""
    return hashlib.sha256(RCPT_MAGIC + bytes(message_oid) + recipient.lower().encode("utf-8")).digest()[:16]


def is_receipt(obj: dict[str, Any]) -> bool:
    return obj.get("k") == KIND_DISPATCH_RCPT


def receipt_problem(obj: dict[str, Any]) -> str:
    """Rules a signature can't express: the id is derived (one receipt per
    person per message), and a direct conversation's receipt comes from one
    of its two people. "" when fine, else an error code."""
    try:
        if bytes(obj["o"]) != receipt_oid(bytes(obj["m"]), str(obj["u"])):
            return "invalid_payload"
    except (KeyError, TypeError, ValueError):
        return "invalid_payload"
    conv = str(obj.get("v", ""))
    if conv.startswith("dm:") and str(obj["u"]).lower() not in conv[3:].split(":", 1):
        return "bad_signature"
    return ""


def canonical_bytes(obj: dict[str, Any]) -> bytes:
    kind = obj.get("k")
    if kind not in FIELDS:
        raise CertError("unknown object kind")
    out = bytearray(MAGIC)
    for name in FIELDS[kind]:
        if name not in obj:
            raise CertError(f"missing field {name}")
        value = obj[name]
        if name in INT_FIELDS:
            if not isinstance(value, int) or value < 0:
                raise CertError(f"field {name} must be a non-negative int")
            raw = int(value).to_bytes(8, "big")
        elif name in BYTES_FIELDS:
            if not isinstance(value, (bytes, bytearray)) or len(value) != BYTES_FIELDS[name]:
                raise CertError(f"field {name} must be {BYTES_FIELDS[name]} bytes")
            raw = bytes(value)
        else:
            if not isinstance(value, str):
                raise CertError(f"field {name} must be text")
            raw = value.encode("utf-8")
        if len(raw) > 0xFFFF:
            raise CertError(f"field {name} too long")
        out += name.encode("ascii") + b":" + len(raw).to_bytes(2, "big") + raw
    return bytes(out)


class OfflineVerifier:
    """Checks a signed object with nothing but cached certificates — what an
    Outpost or Scout does with Station out of reach (docs/identity.md)."""

    def __init__(self, community_public: bytes, *, clock=None) -> None:
        import time

        self.community_public = bytes(community_public)
        self.identities: dict[bytes, dict[str, Any]] = {}  # identity id -> id certificate
        self.revoked: set[int] = set()
        self._clock = clock or time.time

    def add_cert(self, cert: dict[str, Any]) -> bool:
        from server.services.identity import certs as C

        if not cert or not C.verify(cert, self.community_public):
            return False
        if cert["k"] == C.KIND_IDENTITY:
            self.identities[bytes(cert["i"])] = cert
        elif cert["k"] == C.KIND_REVOCATION:
            self.revoked.add(int(cert["r"]))
        return True

    def owner_of(self, identity_id: bytes) -> str | None:
        cert = self.identities.get(bytes(identity_id))
        return str(cert["u"]) if cert else None

    def verify(self, obj: dict[str, Any]) -> str:
        """Empty string when the object is genuine, else an error code."""
        from server.services.identity import certs as C

        cert = self.identities.get(bytes(obj.get("a") or b""))
        if not cert:
            return "unknown_identity"
        if int(cert["n"]) in self.revoked:
            return "identity_revoked"
        if int(cert["x"]) <= int(self._clock()):
            return "certificate_expired"
        if str(obj.get("u", "")).lower() != str(cert["u"]).lower():
            return "bad_signature"
        if is_receipt(obj):
            problem = receipt_problem(obj)
            if problem:
                return problem
        try:
            message = canonical_bytes({k: v for k, v in obj.items() if k != "s"})
        except CertError:
            return "invalid_payload"
        if not C.verify_signing_key(cert["p"], bytes(obj.get("s") or b""), message):
            return "bad_signature"
        return ""
