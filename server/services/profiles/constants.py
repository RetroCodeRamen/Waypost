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
