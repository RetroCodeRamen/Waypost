"""Corkboard protocol constants — per-outpost public note board."""

from shared.protocol.envelope import (  # noqa: F401  (re-export)
    OP_BOARD_SYNC,
    OP_OUTPOST_CLAIM,
)

MAX_BODY = 500
MAX_SIGNATURE = 80
MAX_DISPLAY_NAME = 80
