"""PROFILE service Waylink operations (see docs/protocol.md)."""

from __future__ import annotations

OP_PAIR_REDEEM = "PAIR_REDEEM"
# Which account is this device bound to? A Scout asks at boot to learn its
# user (and to notice it was unpaired).
OP_WHOAMI = "WHOAMI"
# A device revoking its own binding (Scout Settings -> Unpair). Only ever
# affects env.src itself.
OP_UNPAIR = "UNPAIR"
# Radio-sized people directory for a paired device (Scout contacts).
OP_ROLL_LIST = "ROLL_LIST"
# Offline identity (docs/identity.md, roadmap D2): certificates signed by
# Station's community key.
OP_CERT_ROOT = "CERT_ROOT"  # the community public key (public)
OP_CERT_GET = "CERT_GET"  # a person's identity certificate, by username or identity id
OP_CERT_REVOKED = "CERT_REVOKED"  # revocation certificates, paged
OP_CERT_LIST = "CERT_LIST"  # every person's identity certificate, paged (Outposts cache them all)
# Scout login with username + password (2026-10-05): the Scout derives the
# identity key, signs a one-time challenge; Station binds the Scout.
OP_LOGIN_NONCE = "LOGIN_NONCE"
OP_LOGIN = "LOGIN"
