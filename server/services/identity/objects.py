"""Signed objects (roadmap D3, docs/network-model.md §3).

An object is authored on a device and signed with that device's **signing
key** (the one a ``dev`` certificate vouches for). Anyone holding the
certificates can check who wrote it — Station, an Outpost, another Scout —
whoever carried it. Relays can read what they carry but can't alter or
forge it.

Signed bytes follow the certificate convention (certs.py):

    b"WAYPOST-OBJ-1\\n" + name:len:value for each field in the kind's order

First kind: ``dispatch.msg``

    k  "dispatch.msg"
    o  object id, 16 random bytes (also the message id: o.hex())
    u  author's username (from the certificate, so it can't be mixed up)
    c  serial of the author's device certificate
    v  conversation id (dm:<a>:<b> for direct messages, room:<slug>)
    b  body text
    t  created, seconds (the author device's clock; informative)
"""

from __future__ import annotations

import os
from typing import Any

from server.services.identity.certs import CertError

MAGIC = b"WAYPOST-OBJ-1\n"
KIND_DISPATCH_MSG = "dispatch.msg"

FIELDS: dict[str, tuple[str, ...]] = {
    KIND_DISPATCH_MSG: ("k", "o", "u", "c", "v", "b", "t"),
}
INT_FIELDS = {"c", "t"}
BYTES_FIELDS = {"o": 16}


def new_oid() -> bytes:
    return os.urandom(16)


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
        self.devices: dict[int, dict[str, Any]] = {}
        self.revoked: set[int] = set()
        self._clock = clock or time.time

    def add_cert(self, cert: dict[str, Any]) -> bool:
        from server.services.identity import certs as C

        if not C.verify(cert, self.community_public):
            return False
        if cert["k"] == C.KIND_DEVICE:
            self.devices[int(cert["n"])] = cert
        elif cert["k"] == C.KIND_REVOCATION:
            self.revoked.add(int(cert["r"]))
        return True

    def owner_of(self, serial: int) -> str | None:
        cert = self.devices.get(int(serial))
        return str(cert["u"]) if cert else None

    def verify(self, obj: dict[str, Any]) -> str:
        """Empty string when the object is genuine, else an error code."""
        from server.services.identity import certs as C

        cert = self.devices.get(int(obj.get("c", -1)))
        if not cert:
            return "unknown_certificate"
        if int(cert["n"]) in self.revoked:
            return "certificate_revoked"
        if int(cert["x"]) <= int(self._clock()):
            return "certificate_expired"
        if str(obj.get("u", "")).lower() != str(cert["u"]).lower():
            return "bad_signature"
        try:
            message = canonical_bytes({k: v for k, v in obj.items() if k != "s"})
        except CertError:
            return "invalid_payload"
        if not C.verify_signing_key(cert["p"], bytes(obj.get("s") or b""), message):
            return "bad_signature"
        return ""
