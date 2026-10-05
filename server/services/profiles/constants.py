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
OP_CERT_ISSUE = "CERT_ISSUE"  # device certificate for this device's signing key
OP_CERT_GET = "CERT_GET"  # a person's identity certificate (+ device count)
OP_CERT_DEV = "CERT_DEV"  # one of a person's device certificates, by index
OP_CERT_REVOKED = "CERT_REVOKED"  # revocation certificates, paged
