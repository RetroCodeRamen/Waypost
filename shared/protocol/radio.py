"""Fit Waylink replies into one encrypted Reticulum packet.

A Pocket over LoRa can only receive what fits in a single encrypted
Reticulum packet: RNS.Packet.ENCRYPTED_MDU = 383 bytes of plaintext, and
the CBOR envelope alone costs ~210 of them. Anything larger never arrives
(microReticulum on the device has no Resource transfer in use), so replies
meant for the radio are sized here by *encoding them and measuring*,
not by estimating, and long text moves in byte-offset chunks.

The gateway encodes exactly the envelope a service returns (it only
resolves the transport destination), so a size measured here is the size
on the wire.
"""

from __future__ import annotations

from typing import Any, Callable

from shared.protocol.envelope import Envelope, encode_cbor

RADIO_MDU = 383  # RNS.Packet.ENCRYPTED_MDU
CHUNK_DEFAULT = 160


def chunk_utf8(text: str, offset: int, limit: int) -> tuple[str, int]:
    """Return (slice, total_bytes) for `limit` bytes of `text`'s UTF-8 form
    starting at byte `offset`, never splitting a multibyte character.
    Offsets handed back to clients are always character boundaries, so an
    offset inside a character is clamped back to its start."""
    raw = (text or "").encode("utf-8")
    total = len(raw)
    start = max(0, min(int(offset), total))
    while start > 0 and start < total and (raw[start] & 0xC0) == 0x80:
        start -= 1
    end = min(total, start + max(4, int(limit)))
    while end < total and (raw[end] & 0xC0) == 0x80:
        end -= 1
    return raw[start:end].decode("utf-8"), total


def fit_text_reply(
    build: Callable[[str], Envelope],
    text: str,
    offset: int,
    limit: int,
    *,
    mdu: int = RADIO_MDU,
) -> Envelope:
    """Build a chunked-text reply with `build(slice)`, shrinking the slice
    until the encoded envelope fits in one packet."""
    limit = max(4, min(int(limit or CHUNK_DEFAULT), mdu))
    while True:
        piece, _total = chunk_utf8(text, offset, limit)
        env = build(piece)
        over = len(encode_cbor(env)) - mdu
        if over <= 0 or limit <= 4:
            return env
        limit = max(4, limit - over)


def fit_list_reply(
    build: Callable[[list[Any], bool], Envelope],
    items: list[Any],
    *,
    mdu: int = RADIO_MDU,
) -> tuple[Envelope, int]:
    """Pack as many leading `items` as fit; `build(items, more)` makes the
    envelope. Returns (envelope, count_packed). Always packs at least one
    item when any exist, so paging can't stall."""
    count = len(items)
    while True:
        env = build(items[:count], count < len(items))
        if count <= 1 or len(encode_cbor(env)) <= mdu:
            return env, count
        count -= 1
