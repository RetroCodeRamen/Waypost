"""Reticulum Waylink transport — encrypted production path (M2e).

Uses the Reticulum Network Stack (`rns`) so on-air / AutoInterface traffic is
authenticated and encrypted by the transport. Application envelopes remain
opaque CBOR payloads.

Do not import ``RNS`` at module load so environments without ``rns`` still
import this stub cleanly; install with ``pip install rns``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from server.transports.base import (
    LinkQuality,
    RouteInfo,
    Transport,
    TransportPacket,
)

logger = logging.getLogger("waypost.transport.reticulum")

APP_NAME = "waypost"
ASPECT = "waylink"


def _default_config(
    config_dir: Path,
    *,
    control_port: int = 37429,
    interface: str = "auto",
    tcp_host: str = "127.0.0.1",
    tcp_port: int = 4242,
) -> None:
    """Write a Reticulum config if missing.

    ``interface``:
      - ``auto`` — AutoInterface (one instance per host / LAN discovery)
      - ``tcp_server`` / ``tcp_client`` — same-host encrypted lab path (M2e ping)
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = config_dir / "config"
    if cfg.exists():
        return

    if interface == "tcp_server":
        iface = f"""
[interfaces]
  [[TCP Server]]
    type = TCPServerInterface
    enabled = Yes
    listen_ip = {tcp_host}
    listen_port = {tcp_port}
"""
    elif interface == "tcp_client":
        iface = f"""
[interfaces]
  [[TCP Client]]
    type = TCPClientInterface
    enabled = Yes
    target_host = {tcp_host}
    target_port = {tcp_port}
"""
    else:
        iface = """
[interfaces]
  [[Auto Interface]]
    type = AutoInterface
    enabled = Yes
"""

    cfg.write_text(
        f"""
[reticulum]
  enable_transport = Yes
  share_instance = No
  shared_instance_port = {control_port - 1}
  instance_control_port = {control_port}
  panic_on_interface_error = No

[logging]
  loglevel = 4
{iface}
""".lstrip()
    )


class ReticulumTransport(Transport):
    """Encrypted Waylink transport via Reticulum (AutoInterface or RNode)."""

    name = "reticulum"

    def __init__(
        self,
        device_path: str = "/dev/waypost-lora",
        *,
        config_dir: Optional[str | Path] = None,
        identity_path: Optional[str | Path] = None,
        control_port: int = 37429,
        node_id: str = "station",
        interface: str = "auto",
        tcp_host: str = "127.0.0.1",
        tcp_port: int = 4242,
    ) -> None:
        self.device_path = device_path
        self.config_dir = Path(config_dir) if config_dir else Path("data/reticulum")
        self.identity_path = (
            Path(identity_path) if identity_path else self.config_dir / "identity"
        )
        self.control_port = control_port
        self.node_id = node_id
        self.interface = interface
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self._running = False
        self._rns = None
        self._identity = None
        self._destination = None
        self._inbox: asyncio.Queue[TransportPacket] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._dest_cache: dict[str, object] = {}
        self._peer_routes: dict[str, str] = {}  # logical node_id → dest hash
        self._lock = threading.Lock()

    def learn_route(self, node_id: str, transport_dest: str) -> None:
        """Map a logical Waylink node_id to a Reticulum destination hash."""
        raw = transport_dest.strip().lower().replace(":", "")
        if len(raw) != 32 or any(c not in "0123456789abcdef" for c in raw):
            raise ValueError(f"transport_dest must be 32 hex chars, got {transport_dest!r}")
        with self._lock:
            self._peer_routes[node_id] = raw
            self._dest_cache.pop(node_id, None)
        logger.info("learned_route node=%s dest=%s", node_id, raw)

    def resolve_destination(self, destination: str) -> str:
        """Resolve logical node_id to RNS hash when known; else return as-is."""
        with self._lock:
            return self._peer_routes.get(destination, destination)

    @property
    def destination_hash_hex(self) -> Optional[str]:
        if self._destination is None:
            return None
        import RNS

        return RNS.hexrep(self._destination.hash, delimit=False)

    async def start(self) -> None:
        try:
            import RNS
        except ImportError as exc:
            raise RuntimeError(
                "rns is required for ReticulumTransport — pip install rns"
            ) from exc

        _default_config(
            self.config_dir,
            control_port=self.control_port,
            interface=self.interface,
            tcp_host=self.tcp_host,
            tcp_port=self.tcp_port,
        )
        self._rns = RNS.Reticulum(str(self.config_dir))

        if self.identity_path.exists():
            self._identity = RNS.Identity.from_file(str(self.identity_path))
        else:
            self._identity = RNS.Identity()
            self.identity_path.parent.mkdir(parents=True, exist_ok=True)
            self._identity.to_file(str(self.identity_path))

        self._destination = RNS.Destination(
            self._identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            APP_NAME,
            ASPECT,
        )
        self._destination.set_packet_callback(self._on_packet)
        self._destination.announce()

        self._loop = asyncio.get_running_loop()
        self._running = True
        logger.info(
            "ReticulumTransport started node=%s hash=%s config=%s",
            self.node_id,
            self.destination_hash_hex,
            self.config_dir,
        )

    def _on_packet(self, data: bytes, packet) -> None:
        if not self._running or self._loop is None:
            return
        src = None
        try:
            import RNS

            if packet and getattr(packet, "destination_hash", None):
                src = RNS.hexrep(packet.destination_hash, delimit=False)
        except Exception:
            src = None
        tp = TransportPacket(
            destination=self.node_id,
            payload=bytes(data),
            source=src,
            metadata={"encrypted": True, "transport": "reticulum"},
        )
        self._loop.call_soon_threadsafe(self._inbox.put_nowait, tp)

    async def stop(self) -> None:
        self._running = False
        self._destination = None
        self._identity = None
        # Reticulum is process-global; do not tear down mid-process in tests
        # that may start another transport later.
        self._rns = None

    def _out_destination(self, destination: str):
        """Resolve or build an OUT destination.

        ``destination`` may be:
        - 32-byte hex destination hash (preferred)
        - path to a peer public-key / identity file (lab)
        """
        import RNS

        with self._lock:
            if destination in self._dest_cache:
                return self._dest_cache[destination]

            dest_hash = None
            identity = None
            raw = destination.strip().lower().replace(":", "")
            if len(raw) == 32 and all(c in "0123456789abcdef" for c in raw):
                dest_hash = bytes.fromhex(raw)
            elif Path(destination).exists():
                identity = RNS.Identity.from_file(destination)
            else:
                raise ValueError(
                    f"Unknown Reticulum destination {destination!r} "
                    "(need 32-hex hash or identity file path)"
                )

            if identity is not None:
                out = RNS.Destination(
                    identity,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    APP_NAME,
                    ASPECT,
                )
            else:
                # Materialize from known hash after path discovery (retry — TCP
                # peers need a moment for announces to propagate).
                identity = None
                last_err: Exception | None = None
                for attempt in range(12):
                    try:
                        RNS.Transport.request_path(dest_hash)
                    except Exception as exc:
                        last_err = exc
                    identity = RNS.Identity.recall(dest_hash)
                    if identity is not None:
                        break
                    time.sleep(0.5)
                if identity is None:
                    raise RuntimeError(
                        f"No path/identity recalled for {raw}; peer must announce first"
                        + (f" ({last_err})" if last_err else "")
                    )
                out = RNS.Destination(
                    identity,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    APP_NAME,
                    ASPECT,
                )
            self._dest_cache[destination] = out
            return out

    async def send(self, packet: TransportPacket) -> None:
        if not self._running:
            raise RuntimeError("ReticulumTransport is not started")

        def _send() -> None:
            dest = self.resolve_destination(packet.destination)
            out = self._out_destination(dest)
            import RNS

            rns_packet = RNS.Packet(out, packet.payload)
            rns_packet.send()

        await asyncio.to_thread(_send)

    async def receive_one(self, timeout: float | None = 2.0) -> TransportPacket:
        if timeout is None:
            return await self._inbox.get()
        return await asyncio.wait_for(self._inbox.get(), timeout=timeout)

    def receive(self) -> AsyncIterator[TransportPacket]:
        async def _gen() -> AsyncIterator[TransportPacket]:
            while self._running:
                pkt = await self._inbox.get()
                yield pkt

        return _gen()

    async def reachable(self, destination: str) -> bool:
        try:
            await asyncio.to_thread(self._out_destination, destination)
            return True
        except Exception:
            return False

    async def get_route(self, destination: str) -> Optional[RouteInfo]:
        ok = await self.reachable(destination)
        if not ok:
            return None
        return RouteInfo(
            destination=destination,
            hops=None,
            detail={"transport": "reticulum", "encrypted": True},
        )

    async def get_link_quality(self, destination: str) -> LinkQuality:
        return LinkQuality.GOOD if await self.reachable(destination) else LinkQuality.UNKNOWN
