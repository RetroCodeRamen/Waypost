"""Beacon protocol constants — emergency / high-priority alerts."""

OP_BEACON_GET = "BEACON_GET"
OP_BEACON_PUSH = "BEACON_PUSH"
OP_BEACON_CLEAR = "BEACON_CLEAR"
OP_BEACON_LIST = "BEACON_LIST"

MAX_BODY = 2000
MAX_TITLE = 120

# Minimum seconds between pushes from the same author (flood control)
PUSH_COOLDOWN_SEC = 30
