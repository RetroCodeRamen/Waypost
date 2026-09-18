"""Mock Waylink transport for development without radios.

Simulates latency, packet loss, duplicate delivery, disconnects, and queueing.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Deque, Dict, Optional, Set

from server.transports.base import (
    LinkQuality,
    RouteInfo,
    Transport,
    TransportPacket,
)


@dataclass
class MockNodeConfig:
    node_id: str
    connected: bool = True
    hops_to: Dict[str, int] = field(default_factory=dict)


@dataclass
class MockTransportConfig:
    """Behavior knobs for the simulated mesh."""

    latency_ms_min: int = 20
    latency_ms_max: int = 200
    loss_rate: float = 0.0
    duplicate_rate: float = 0.0
    bandwidth_bytes_per_sec: Optional[int] = None  # None = unlimited
    seed: Optional[int] = None


class MockTransport(Transport):
    """In-process multi-node mock mesh.

    Create one MockMesh and obtain a MockTransport per node via mesh.attach(node_id).
    """

    name = "mock"

    def __init__(
        self,
        node_id: str,
        mesh: "MockMesh",
        config: Optional[MockTransportConfig] = None,
    ) -> None:
        self.node_id = node_id
        self._mesh = mesh
        self._config = config or MockTransportConfig()
        self._rng = random.Random(self._config.seed)
        self._inbox: asyncio.Queue[TransportPacket] = asyncio.Queue()
        self._running = False
        self._seen: Deque[str] = deque(maxlen=2048)
        self._seen_set: Set[str] = set()

    async def start(self) -> None:
        self._running = True
        self._mesh.register(self)

    async def stop(self) -> None:
        self._running = False
        self._mesh.unregister(self.node_id)

    async def send(self, packet: TransportPacket) -> None:
        if not self._running:
            raise RuntimeError("MockTransport is not started")
        source = packet.source or self.node_id
        outbound = TransportPacket(
            destination=packet.destination,
            payload=packet.payload,
            source=source,
            message_id=packet.message_id,
            ttl=packet.ttl,
            metadata=dict(packet.metadata),
        )
        await self._mesh.deliver(self.node_id, outbound, self._config, self._rng)

    async def receive(self) -> AsyncIterator[TransportPacket]:
        while self._running:
            packet = await self._inbox.get()
            yield packet

    async def receive_one(self, timeout: float | None = 2.0) -> TransportPacket:
        """Wait for one inbound packet. timeout=None waits indefinitely."""
        if timeout is None:
            return await self._inbox.get()
        return await asyncio.wait_for(self._inbox.get(), timeout=timeout)

    async def reachable(self, destination: str) -> bool:
        return self._mesh.is_reachable(self.node_id, destination)

    async def get_route(self, destination: str) -> Optional[RouteInfo]:
        return self._mesh.get_route(self.node_id, destination)

    async def get_link_quality(self, destination: str) -> LinkQuality:
        if not await self.reachable(destination):
            return LinkQuality.UNKNOWN
        hops = (await self.get_route(destination))
        if hops is None or hops.hops is None:
            return LinkQuality.FAIR
        if hops.hops <= 1:
            return LinkQuality.EXCELLENT
        if hops.hops == 2:
            return LinkQuality.GOOD
        if hops.hops == 3:
            return LinkQuality.FAIR
        return LinkQuality.POOR

    def _enqueue(self, packet: TransportPacket) -> None:
        mid = packet.message_id
        if mid:
            if mid in self._seen_set:
                return
            if len(self._seen) == self._seen.maxlen:
                old = self._seen.popleft()
                self._seen_set.discard(old)
            self._seen.append(mid)
            self._seen_set.add(mid)
        self._inbox.put_nowait(packet)


class MockMesh:
    """Shared fabric connecting MockTransport instances."""

    def __init__(self) -> None:
        self._nodes: Dict[str, MockTransport] = {}
        self._node_meta: Dict[str, MockNodeConfig] = {}
        self._adjacency: Dict[str, Set[str]] = defaultdict(set)
        self._queued: Deque[tuple[str, TransportPacket, float]] = deque()

    def attach(
        self,
        node_id: str,
        config: Optional[MockTransportConfig] = None,
        *,
        connected: bool = True,
    ) -> MockTransport:
        transport = MockTransport(node_id, self, config)
        self._node_meta[node_id] = MockNodeConfig(node_id=node_id, connected=connected)
        return transport

    def register(self, transport: MockTransport) -> None:
        self._nodes[transport.node_id] = transport

    def unregister(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)

    def link(self, a: str, b: str) -> None:
        self._adjacency[a].add(b)
        self._adjacency[b].add(a)

    def set_connected(self, node_id: str, connected: bool) -> None:
        if node_id in self._node_meta:
            self._node_meta[node_id].connected = connected

    def is_reachable(self, source: str, destination: str) -> bool:
        if source == destination:
            return True
        src_meta = self._node_meta.get(source)
        dst_meta = self._node_meta.get(destination)
        if not src_meta or not dst_meta:
            return False
        if not src_meta.connected or not dst_meta.connected:
            return False
        return self.get_route(source, destination) is not None

    def get_route(self, source: str, destination: str) -> Optional[RouteInfo]:
        if source == destination:
            return RouteInfo(destination=destination, hops=0, path=(source,))
        if source not in self._adjacency and destination not in self._nodes:
            return None
        # BFS
        queue: Deque[tuple[str, tuple[str, ...]]] = deque([(source, (source,))])
        visited = {source}
        while queue:
            node, path = queue.popleft()
            for neighbor in self._adjacency.get(node, ()):
                if neighbor in visited:
                    continue
                new_path = path + (neighbor,)
                if neighbor == destination:
                    hops = len(new_path) - 1
                    return RouteInfo(
                        destination=destination,
                        hops=hops,
                        next_hop=new_path[1] if hops else None,
                        path=new_path,
                    )
                visited.add(neighbor)
                queue.append((neighbor, new_path))
        # Fully connected fallback when no explicit links: all started nodes see each other at 1 hop
        if not any(self._adjacency.values()) and destination in self._nodes and source in self._nodes:
            src = self._node_meta.get(source)
            dst = self._node_meta.get(destination)
            if src and dst and src.connected and dst.connected:
                return RouteInfo(
                    destination=destination,
                    hops=1,
                    next_hop=destination,
                    path=(source, destination),
                )
        return None

    async def deliver(
        self,
        from_node: str,
        packet: TransportPacket,
        config: MockTransportConfig,
        rng: random.Random,
    ) -> None:
        if rng.random() < config.loss_rate:
            return

        route = self.get_route(from_node, packet.destination)
        if route is None:
            # Queue conceptually: drop for now; callers may retry
            return

        delay = rng.randint(config.latency_ms_min, config.latency_ms_max) / 1000.0
        if config.bandwidth_bytes_per_sec:
            delay += len(packet.payload) / config.bandwidth_bytes_per_sec

        await asyncio.sleep(delay)

        target = self._nodes.get(packet.destination)
        if target is None:
            return
        meta = self._node_meta.get(packet.destination)
        if meta and not meta.connected:
            return

        target._enqueue(packet)
        if rng.random() < config.duplicate_rate:
            # Simulated duplicate delivery
            await asyncio.sleep(delay * 0.1)
            target._enqueue(packet)
