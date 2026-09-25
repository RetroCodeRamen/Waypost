"""Waylink transport abstraction.

Application code depends on Transport, not on Reticulum or any specific radio stack.
User-facing name for this layer: Waylink.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional


class LinkQuality(str, Enum):
    UNKNOWN = "unknown"
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"
    EXCELLENT = "excellent"


@dataclass(frozen=True)
class RouteInfo:
    """Logical route description (hops / next hop). Transport-specific details stay opaque."""

    destination: str
    hops: Optional[int] = None
    next_hop: Optional[str] = None
    path: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransportPacket:
    """Opaque payload bytes plus addressing used by the gateway."""

    destination: str
    payload: bytes
    source: Optional[str] = None
    message_id: Optional[str] = None
    ttl: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Transport(ABC):
    """Waylink transport interface."""

    name: str = "transport"

    # Optional hook: called when a genuine Outpost announce carries the
    # auto-claim marker (node_id, transport_dest, display_name). None means
    # "not supported by this transport" -- only ReticulumTransport actually
    # fires it. A settable attribute rather than an abstract method so
    # callers (main.py) can wire it up after construction, once
    # PairingService exists. Declared here so every Transport exposes it
    # without a hasattr() guard at the call site -- a broken wire-up on a
    # transport that's supposed to support this now silently no-ops the
    # same documented way instead of behaving differently per transport.
    on_unclaimed_outpost_announce: Optional[
        Callable[[str, str, Optional[str]], None]
    ] = None

    @abstractmethod
    async def start(self) -> None:
        """Bring up the transport."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear down the transport."""

    @abstractmethod
    async def send(self, packet: TransportPacket) -> None:
        """Send a packet toward destination (may queue)."""

    @abstractmethod
    def receive(self) -> AsyncIterator[TransportPacket]:
        """Async iterator of inbound packets."""

    @abstractmethod
    async def reachable(self, destination: str) -> bool:
        """Return True if destination is believed reachable now."""

    @abstractmethod
    async def get_route(self, destination: str) -> Optional[RouteInfo]:
        """Return route info if known."""

    @abstractmethod
    async def get_link_quality(self, destination: str) -> LinkQuality:
        """Return qualitative link estimate."""

    def learn_route(self, node_id: str, transport_dest: str) -> None:
        """Map a logical Waylink node_id to a transport-specific destination.

        No-op by default -- only transports with an addressable routing
        layer of their own (Reticulum) need to override this.
        """
        return None

    def resolve_destination(self, destination: str) -> str:
        """Resolve a logical node_id to a transport-specific destination.

        Identity by default -- most transports already address by node_id
        directly, so there's nothing to resolve.
        """
        return destination

    @property
    def destination_hash_hex(self) -> Optional[str]:
        """This transport's own destination hash, hex-encoded, if it has one."""
        return None
