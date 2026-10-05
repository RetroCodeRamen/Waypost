"""A person's Waypost identity key, derived from username + password
(decided 2026-10-05; docs/identity.md "Identity from username + password").

The same username and password give the same key on any device — the
Outpost's Wi-Fi page (computed in the browser, so the password never leaves
the phone), a Scout, Station's portal — with no Station needed to log in. A
different password is a different identity, so reusing someone's username
can't intercept their friends' messages: contacts are pinned by key.

    seed = scrypt(password (UTF-8), salt = "waypost-identity-v1\\n" + lower(username),
                  N = 4096, r = 8, p = 4, 32 bytes)
    key  = Ed25519 private key with that seed
    id   = SHA-256(public key)[:16]

scrypt is slow and memory-hard (4 MiB) so guessing passwords offline
against a public key is expensive; with a 10-character minimum that's the
protection. Parameters are fixed by the Scout's memory (PSRAM) and must
never change without a new salt prefix. The browser (firmware/outpost web
page) and the Scout (firmware/pocket) compute the same thing — a pinned
vector in server/tests/test_identity_keys.py is checked by both.
"""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SALT_PREFIX = b"waypost-identity-v1\n"
SCRYPT_N = 4096
SCRYPT_R = 8
SCRYPT_P = 4  # 4 passes: ~4.4 s on a Scout, ~1-2 s in a phone browser (measured/estimated 2026-10-05)
MIN_PASSWORD = 10


def derive_seed(username: str, password: str) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=SALT_PREFIX + username.strip().lower().encode("utf-8"),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    )


def private_key(username: str, password: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(derive_seed(username, password))


def public_key(username: str, password: str) -> bytes:
    return private_key(username, password).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def identity_id(public: bytes) -> bytes:
    return hashlib.sha256(bytes(public)).digest()[:16]
