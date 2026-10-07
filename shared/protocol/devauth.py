"""Device request authentication (review 2026-10-07).

A Reticulum packet is encrypted *to* Station but says nothing about who
sent it; a Waylink envelope's ``src`` is just text the sender wrote. So
bound devices prove themselves with a key Station gave them at sign-in
(``dk`` in the LOGIN / PAIR_REDEEM reply, which only that device can read —
it is encrypted to its own destination):

    mid = r + tag        r: 8 random hex characters
    tag = HMAC-SHA256(device key, MAGIC + src + "\\n" + r)[:4], as 8 hex

Nothing grows: ``mid`` was already 16 hex characters. Every request is
encrypted on the way, so nobody else ever sees a valid tag, and Reticulum
drops replayed packets; a forger must guess 32 bits per try.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

MAGIC = b"WAYPOST-DEV-1\n"
KEY_LEN = 16


def new_key() -> bytes:
    return secrets.token_bytes(KEY_LEN)


def tag(key: bytes, src: str, nonce: str) -> str:
    return hmac.new(bytes(key), MAGIC + src.encode("utf-8") + b"\n" + nonce.encode("ascii"),
                    hashlib.sha256).digest()[:4].hex()


def make_mid(key: bytes, src: str) -> str:
    nonce = secrets.token_hex(4)
    return nonce + tag(key, src, nonce)


def check(key: bytes, src: str, mid: str) -> bool:
    if not isinstance(mid, str) or len(mid) != 16:
        return False
    try:
        nonce = mid[:8]
        nonce.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(mid[8:].lower(), tag(key, src, nonce))
