"""Trailhead protocol constants — see docs/protocol.md "Trailhead"."""

OP_TRAIL_GET = "TRAIL_GET"

HOME_PATH = "home"
MAX_PATH = 64
MAX_TITLE = 80
# A Pocket fetches ~160 bytes per LoRa round trip (~2 s), so 8 KB is
# already a ~2-minute read. Keep Trailhead pages short on purpose.
MAX_BODY = 8_000
