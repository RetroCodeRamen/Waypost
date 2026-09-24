"""Waylink RPC envelope and constants (protocol v1)."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import IntFlag
from typing import Any, Optional

PROTOCOL_VERSION = 1


class Flags(IntFlag):
    NONE = 0
    REQUEST = 1 << 0
    RESPONSE = 1 << 1
    ERROR = 1 << 2
    ACK = 1 << 3
    QUEUED = 1 << 4


# Service identifiers (radio-facing; keep concise)
SVC_CORE = "CORE"
SVC_DISPATCH = "DISPATCH"
SVC_MAIL = "MAIL"
SVC_FIELDBOOK = "FIELDBOOK"
SVC_PROFILE = "PROFILE"
SVC_COMMONS = "COMMONS"
SVC_NOTICEBOARD = "NOTICEBOARD"
SVC_BEACON = "BEACON"
SVC_LOCKER = "LOCKER"
SVC_FINDER = "FINDER"
SVC_SYNC = "SYNC"
SVC_SIGNAL = "SIGNAL"
SVC_CORKBOARD = "CORKBOARD"

# Core ops
OP_PING = "PING"
OP_PONG = "PONG"

# Dispatch ops (see docs/protocol.md)
OP_MSG_SEND = "MSG_SEND"
OP_MSG_LIST = "MSG_LIST"
OP_MSG_ACK = "MSG_ACK"
OP_MSG_SYNC = "MSG_SYNC"
OP_MSG_PUSH = "MSG_PUSH"

# Corkboard ops (see docs/protocol.md)
OP_BOARD_SYNC = "BOARD_SYNC"
OP_OUTPOST_CLAIM = "OUTPOST_CLAIM"


def new_id() -> str:
    """16 hex chars — short enough for LoRa frames, unique enough for Station scale."""
    return uuid.uuid4().hex[:16]


@dataclass
class Envelope:
    """Versioned Waylink RPC envelope.

    Field names match docs/protocol.md abbreviated keys when serialized.
    """

    v: int = PROTOCOL_VERSION
    mid: str = field(default_factory=new_id)
    rid: str = field(default_factory=new_id)
    src: str = ""
    dst: str = ""
    svc: str = SVC_CORE
    op: str = OP_PING
    flags: int = int(Flags.REQUEST)
    ts: int = field(default_factory=lambda: int(time.time()))
    ttl: int = 8
    payload: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        return cls(
            v=int(data.get("v", PROTOCOL_VERSION)),
            mid=str(data.get("mid") or new_id()),
            rid=str(data.get("rid") or new_id()),
            src=str(data.get("src") or ""),
            dst=str(data.get("dst") or ""),
            svc=str(data.get("svc") or SVC_CORE),
            op=str(data.get("op") or OP_PING),
            flags=int(data.get("flags") or 0),
            ts=int(data.get("ts") or int(time.time())),
            ttl=int(data.get("ttl") or 8),
            payload=data.get("payload"),
        )

    def make_response(
        self,
        *,
        op: str,
        payload: Any = None,
        flags: Flags = Flags.RESPONSE,
        error: bool = False,
    ) -> "Envelope":
        f = int(flags)
        if error:
            f |= int(Flags.ERROR)
        return Envelope(
            v=PROTOCOL_VERSION,
            mid=new_id(),
            rid=self.rid,
            src=self.dst,
            dst=self.src,
            svc=self.svc,
            op=op,
            flags=f,
            ttl=self.ttl,
            payload=payload,
        )


def encode_cbor(envelope: Envelope) -> bytes:
    try:
        import cbor2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("cbor2 is required for CBOR encoding") from exc
    return cbor2.dumps(envelope.to_dict())


def decode_cbor(data: bytes) -> Envelope:
    try:
        import cbor2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("cbor2 is required for CBOR decoding") from exc
    obj = cbor2.loads(data)
    if not isinstance(obj, dict):
        raise ValueError("CBOR envelope must be a map")
    return Envelope.from_dict(obj)


def encode_json(envelope: Envelope) -> bytes:
    import json

    return json.dumps(envelope.to_dict(), separators=(",", ":")).encode("utf-8")


def decode_json(data: bytes) -> Envelope:
    import json

    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("JSON envelope must be an object")
    return Envelope.from_dict(obj)
