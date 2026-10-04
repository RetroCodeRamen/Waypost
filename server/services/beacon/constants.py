"""Beacon protocol constants — emergency / high-priority alerts."""

OP_BEACON_GET = "BEACON_GET"
OP_BEACON_PUSH = "BEACON_PUSH"
OP_BEACON_CLEAR = "BEACON_CLEAR"
OP_BEACON_LIST = "BEACON_LIST"
OP_BEACON_SYNC = "BEACON_SYNC"
# Station -> every paired radio device when a Beacon is raised or cleared.
OP_BEACON_ALERT = "BEACON_ALERT"

MAX_BODY = 2000
MAX_TITLE = 120

# Minimum seconds between pushes from the same author (flood control)
PUSH_COOLDOWN_SEC = 30
