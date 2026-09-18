"""Shared protocol package."""

from shared.protocol.envelope import (
    PROTOCOL_VERSION,
    Envelope,
    Flags,
    OP_PING,
    OP_PONG,
    SVC_CORE,
    SVC_DISPATCH,
    SVC_MAIL,
    decode_cbor,
    decode_json,
    encode_cbor,
    encode_json,
    new_id,
)

__all__ = [
    "PROTOCOL_VERSION",
    "Envelope",
    "Flags",
    "OP_PING",
    "OP_PONG",
    "SVC_CORE",
    "SVC_DISPATCH",
    "SVC_MAIL",
    "decode_cbor",
    "decode_json",
    "encode_cbor",
    "encode_json",
    "new_id",
]
