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
