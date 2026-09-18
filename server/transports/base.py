"""Waylink transport abstraction.

Application code depends on Transport, not on Reticulum or any specific radio stack.
User-facing name for this layer: Waylink.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


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
