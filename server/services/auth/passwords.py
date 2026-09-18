"""Password hashing — PBKDF2-HMAC-SHA256 (stdlib; Stalwart later)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_SCHEME = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return (
        f"{_SCHEME}${_ITERATIONS}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(dk).decode('ascii')}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iters_s, salt_b64, hash_b64 = encoded.split("$", 3)
        if scheme != _SCHEME:
            return False
        iterations = int(iters_s)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False
