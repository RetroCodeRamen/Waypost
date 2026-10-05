"""Waypost certificates — offline-verifiable identity (docs/identity.md,
"Offline identity (target)"; roadmap D2).

A certificate is a small signed record. Station's **community key** (Ed25519)
signs it; any node holding the community public key can check it with no
round trip to Station.

Kinds:
  id   — a person: identity id (16 random bytes, stable), username, display name
  dev  — a device acting for that person: its *signing* key (Ed25519, used to
         author messages; PIN-protected on a Scout) and its Reticulum identity
         hash (its network identity)
  rev  — a revocation of an earlier certificate's serial

What gets signed is a canonical byte string, not CBOR, so Python and the
C++ on Scouts/Outposts produce identical bytes without sharing a CBOR
encoder:

    b"WAYPOST-CERT-1\\n" + for each field, in the kind's fixed order:
        name (ASCII) + b":" + 2-byte big-endian length + value

Integers are 8-byte big-endian, text is UTF-8, bytes are raw. The field name
is part of each entry so no two field layouts can produce the same bytes.
On the wire a certificate is a CBOR map of the same fields plus ``s`` (the
64-byte signature). ``server/tests/test_identity_certs.py`` pins a vector
that the Scout firmware checks too (``firmware/pocket/src/certs.cpp``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

MAGIC = b"WAYPOST-CERT-1\n"

KIND_IDENTITY = "id"
KIND_DEVICE = "dev"
KIND_REVOCATION = "rev"

# Field order per kind; every field is required.
FIELDS: dict[str, tuple[str, ...]] = {
    KIND_IDENTITY: ("k", "n", "i", "u", "dn", "t", "x"),
    KIND_DEVICE: ("k", "n", "i", "u", "p", "d", "t", "x"),
    KIND_REVOCATION: ("k", "n", "r", "t"),
}
INT_FIELDS = {"n", "r", "t", "x"}
BYTES_FIELDS = {"i": 16, "p": 32, "d": 16}  # exact lengths
TEXT_FIELDS = {"k", "u", "dn"}

MAX_DISPLAY_NAME = 40  # bytes; keeps a certificate inside one LoRa packet

# What a device signs (with its Reticulum identity) to ask for a device
# certificate for a signing key: proves the request comes from the device
# Station paired, whatever env.src says.
ISSUE_REQUEST_MAGIC = b"WAYPOST-CERT-REQUEST-1\n"


class CertError(ValueError):
    pass


def _value_bytes(name: str, value: Any) -> bytes:
    if name in INT_FIELDS:
        if not isinstance(value, int) or value < 0:
            raise CertError(f"field {name} must be a non-negative int")
        return int(value).to_bytes(8, "big")
    if name in BYTES_FIELDS:
        if not isinstance(value, (bytes, bytearray)) or len(value) != BYTES_FIELDS[name]:
            raise CertError(f"field {name} must be {BYTES_FIELDS[name]} bytes")
        return bytes(value)
    if name in TEXT_FIELDS:
        if not isinstance(value, str):
            raise CertError(f"field {name} must be text")
        return value.encode("utf-8")
    raise CertError(f"unknown field {name}")


def canonical_bytes(cert: dict[str, Any]) -> bytes:
    kind = cert.get("k")
    if kind not in FIELDS:
        raise CertError("unknown certificate kind")
    out = bytearray(MAGIC)
    for name in FIELDS[kind]:
        if name not in cert:
            raise CertError(f"missing field {name}")
        value = _value_bytes(name, cert[name])
        if len(value) > 0xFFFF:
            raise CertError(f"field {name} too long")
        out += name.encode("ascii") + b":" + len(value).to_bytes(2, "big") + value
    return bytes(out)


def issue_request_bytes(node_id: str, signing_key: bytes) -> bytes:
    return ISSUE_REQUEST_MAGIC + node_id.encode("utf-8") + b"\n" + bytes(signing_key)


def clip_utf8(text: str, limit: int) -> str:
    data = text.encode("utf-8")[:limit]
    return data.decode("utf-8", errors="ignore")


class CommunityKey:
    """The Station's signing key. Private half stays in Station's data
    directory (and its backups); the 32-byte public half goes to every
    device at pairing/claim (``CERT_ROOT``)."""

    def __init__(self, private: Ed25519PrivateKey) -> None:
        self._private = private
        self.public_bytes = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    @classmethod
    def generate(cls) -> "CommunityKey":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed: bytes) -> "CommunityKey":
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    @classmethod
    def load_or_create(cls, path: Path) -> "CommunityKey":
        """32-byte raw seed at ``path``, created (mode 0600) on first use."""
        path = Path(path)
        if path.exists():
            seed = path.read_bytes()
            if len(seed) != 32:
                raise CertError(f"{path} is not a 32-byte community key")
            return cls.from_seed(seed)
        key = cls.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key.seed())
        return key

    def seed(self) -> bytes:
        return self._private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

    def sign(self, cert: dict[str, Any]) -> dict[str, Any]:
        signed = dict(cert)
        signed["s"] = self._private.sign(canonical_bytes(cert))
        return signed


def verify(cert: dict[str, Any], community_public: bytes) -> bool:
    sig = cert.get("s")
    if not isinstance(sig, (bytes, bytearray)) or len(sig) != 64:
        return False
    try:
        body = {k: v for k, v in cert.items() if k != "s"}
        Ed25519PublicKey.from_public_bytes(bytes(community_public)).verify(
            bytes(sig), canonical_bytes(body)
        )
        return True
    except (InvalidSignature, CertError, ValueError):
        return False


def verify_signing_key(public: bytes, signature: bytes, message: bytes) -> bool:
    """Ed25519 check with a device's signing key (used by D3 objects)."""
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public)).verify(bytes(signature), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def is_current(cert: dict[str, Any], now: Optional[int] = None) -> bool:
    import time

    now = int(time.time()) if now is None else now
    return int(cert.get("t", 0)) <= now + 300 and now < int(cert.get("x", 0))
