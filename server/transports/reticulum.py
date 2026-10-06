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
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from shared.protocol.caps import (
    ROLE_STATION,
    ST_SELF,
    STATION_SERVICES,
    Caps,
    app_data as caps_app_data,
    split as split_caps,
)
from server.transports.base import (
    LinkQuality,
    RouteInfo,
    Transport,
    TransportPacket,
)

logger = logging.getLogger("waypost.transport.reticulum")

APP_NAME = "waypost"
ASPECT = "waylink"

# Carried in an Outpost's own Reticulum announce app_data — present only
# while that Outpost is unclaimed *and* its physical-button-toggled
# auto-claim flag is on (see firmware/outpost/src/main.cpp). The hash a
# matching announce carries is already authentic (Reticulum signs it); this
# marker substitutes for the pairing-code flow's "a human typed this, so
# there's real intent behind it" — see docs/security.md.
AUTO_CLAIM_MARKER = b"WPOST-CLAIM:"
# "Who's there?" probes (roadmap D6): PLAIN waypost.nearby, payload starts with this.
NEARBY_ASPECT = "nearby"
NEARBY_PROBE = b"WPN1"
NEARBY_ANSWER_EVERY_S = 30.0
REANNOUNCE_S = 600.0  # Scouts' Nearby forgets a node unheard for 30 min


class _OutpostAnnounceHandler:
    """Bridges RNS.Transport.register_announce_handler's expected shape
    (an object with `aspect_filter` + `received_announce(...)`) to
    ReticulumTransport's own callback — kept as a separate small object so
    RNS's attribute expectations never collide with Transport's own API."""

    aspect_filter = f"{APP_NAME}.{ASPECT}"

    def __init__(self, owner: "ReticulumTransport") -> None:
        self._owner = owner

    def received_announce(self, destination_hash, announced_identity, app_data) -> None:
        self._owner._on_announce(destination_hash, announced_identity, app_data)

_RNODE_BANDWIDTHS = (
    7_800, 10_400, 15_600, 20_800, 31_250, 41_700, 62_500, 125_000, 250_000, 500_000,
)


@dataclass(frozen=True)
class RNodeRadio:
    """LoRa parameters for an RNode. Every node on a mesh must match exactly.

    Frequency and TX power are regulated per region — defaults target the
    US 902–928 MHz ISM band; override via ``WAYPOST_RNS_*`` env vars elsewhere.
    """

    port: str = "/dev/waypost-lora"
    frequency: int = 915_000_000
    bandwidth: int = 125_000
    txpower: int = 14
    spreadingfactor: int = 8
    codingrate: int = 5

    def __post_init__(self) -> None:
        if not 137_000_000 <= self.frequency <= 3_000_000_000:
            raise ValueError(f"RNode frequency out of range: {self.frequency}")
        if self.bandwidth not in _RNODE_BANDWIDTHS:
            raise ValueError(f"RNode bandwidth must be one of {_RNODE_BANDWIDTHS}")
        if not 0 <= self.txpower <= 22:
            raise ValueError(f"RNode txpower must be 0–22 dBm, got {self.txpower}")
        if not 5 <= self.spreadingfactor <= 12:
            raise ValueError("RNode spreadingfactor must be 5–12")
        if not 5 <= self.codingrate <= 8:
            raise ValueError("RNode codingrate must be 5–8")

    @classmethod
    def from_env(cls, port: str) -> "RNodeRadio":
        def _int(name: str, default: int) -> int:
            raw = os.getenv(name)
            return int(raw) if raw else default

        d = cls()
        return cls(
            port=port,
            frequency=_int("WAYPOST_RNS_FREQUENCY", d.frequency),
            bandwidth=_int("WAYPOST_RNS_BANDWIDTH", d.bandwidth),
            txpower=_int("WAYPOST_RNS_TXPOWER", d.txpower),
            spreadingfactor=_int("WAYPOST_RNS_SF", d.spreadingfactor),
            codingrate=_int("WAYPOST_RNS_CR", d.codingrate),
        )


def _default_config(
    config_dir: Path,
    *,
    control_port: int = 37429,
    interface: str = "auto",
    tcp_host: str = "127.0.0.1",
    tcp_port: int = 4242,
    rnode: Optional[RNodeRadio] = None,
) -> None:
    """Write a Reticulum config if missing.

    ``interface``:
      - ``auto`` — AutoInterface (one instance per host / LAN discovery)
      - ``tcp_server`` / ``tcp_client`` — same-host encrypted lab path (M2e ping)
      - ``rnode`` — RNode LoRa radio over USB serial (production Waylink)

    An existing config is never overwritten; delete it to regenerate.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = config_dir / "config"
    if cfg.exists():
        return

    if interface == "rnode":
        r = rnode or RNodeRadio()
        iface = f"""
[interfaces]
  [[RNode LoRa]]
    type = RNodeInterface
    enabled = Yes
    port = {r.port}
    frequency = {r.frequency}
    bandwidth = {r.bandwidth}
    txpower = {r.txpower}
    spreadingfactor = {r.spreadingfactor}
    codingrate = {r.codingrate}
"""
    elif interface == "tcp_server":
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


MANAGED_BEGIN = "  # --- waypost network (managed by Station: WAYPOST_RNS_WIFI, WAYPOST_RNS_UPSTREAM) ---"
MANAGED_END = "  # --- end waypost network ---"
# Earlier name of the block (2026-10-06), removed when found.
_OLD_BEGIN = "  # --- waypost uplinks (managed by Station from WAYPOST_RNS_UPSTREAM) ---"
_OLD_END = "  # --- end waypost uplinks ---"


def parse_upstreams(raw: str) -> list[tuple[str, int]]:
    """``host:port[,host:port...]`` -> [(host, port)]. Bad entries are skipped."""
    out: list[tuple[str, int]] = []
    for item in raw.split(","):
        host, _, port = item.strip().rpartition(":")
        if host and port.isdigit() and 0 < int(port) < 65536:
            out.append((host.strip("[]"), int(port)))
        elif item.strip():
            logger.warning("WAYPOST_RNS_UPSTREAM: ignoring %r (want host:port)", item.strip())
    return out


def _strip_block(text: str, begin: str, end: str) -> str:
    if begin not in text:
        return text
    head, _, rest = text.partition(begin)
    _, _, tail = rest.partition(end)
    return head.rstrip("\n") + "\n" + tail.lstrip("\n")


def apply_network(cfg: Path, *, upstreams: list[tuple[str, int]], wifi_device: str = "",
                  wifi_addr: str = "10.42.0.1", wifi_port: int = 4242) -> None:
    """Keep the config's Station-managed interfaces in step with the settings.

    - ``wifi_device`` (WAYPOST_RNS_WIFI, e.g. wlan0): the Station's own Wi-Fi
      is a Reticulum access point too. An AutoInterface on it (apps there find
      the Station by themselves) and a TCP server on its address (for apps
      where you type one in). Only on that network, never on Ethernet.
    - ``upstreams`` (WAYPOST_RNS_UPSTREAM): TCP links to other Reticulum
      networks (another Station, a hub) over the wired uplink; Reticulum
      reconnects as it comes and goes.

    Devices on the Wi-Fi and LoRa reach whatever is beyond the Station: the
    serving interfaces run in gateway mode (path discovery on behalf of
    clients). Announces from the Wi-Fi or an uplink reach LoRa only within
    the radio's announce cap (2% of airtime by default).
    """
    if not cfg.exists():
        return
    text = _strip_block(cfg.read_text(), _OLD_BEGIN, _OLD_END)
    text = _strip_block(text, MANAGED_BEGIN, MANAGED_END)
    block: list[str] = []
    if wifi_device:
        block += ["  [[WAYPOST Wi-Fi]]", "    type = AutoInterface", "    enabled = Yes",
                  f"    devices = {wifi_device}", "    mode = gateway",
                  "  [[WAYPOST Wi-Fi TCP]]", "    type = TCPServerInterface", "    enabled = Yes",
                  f"    listen_ip = {wifi_addr}", f"    listen_port = {wifi_port}", "    mode = gateway"]
    for i, (host, port) in enumerate(upstreams, 1):
        block += [f"  [[Uplink {i}]]", "    type = TCPClientInterface", "    enabled = Yes",
                  f"    target_host = {host}", f"    target_port = {port}"]
    if block:
        text = text.rstrip("\n") + "\n" + "\n".join([MANAGED_BEGIN, *block, MANAGED_END]) + "\n"
        if "type = RNodeInterface" in text and "mode = gateway\n    port" not in text and \
                "type = RNodeInterface\n    mode = gateway" not in text:
            text = text.replace("type = RNodeInterface", "type = RNodeInterface\n    mode = gateway", 1)
    cfg.write_text(text)


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
        rnode: Optional[RNodeRadio] = None,
    ) -> None:
        self.device_path = device_path
        if interface == "rnode" and rnode is None:
            rnode = RNodeRadio(port=device_path)
        self.rnode = rnode
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
        self._peer_identities: dict[str, object] = {}  # dest hash hex → RNS.Identity
        self._lock = threading.Lock()
        # Set from outside (server/api/main.py), same pattern as
        # WaylinkGateway._resolve_dest — invoked when a genuine Reticulum
        # announce carries the auto-claim marker (node_id, transport_dest,
        # display_name).
        self.on_unclaimed_outpost_announce: Optional[
            Callable[[str, str, Optional[str]], None]
        ] = None
        self._announce_handler: Optional[_OutpostAnnounceHandler] = None
        self._announced_at = 0.0  # time.monotonic() of our last announce
        self._answer_timer: Optional[threading.Timer] = None

    def learn_route(self, node_id: str, transport_dest: str) -> None:
        """Map a logical Waylink node_id to a Reticulum destination hash."""
        raw = transport_dest.strip().lower().replace(":", "")
        if len(raw) != 32 or any(c not in "0123456789abcdef" for c in raw):
            raise ValueError(f"transport_dest must be 32 hex chars, got {transport_dest!r}")
        with self._lock:
            self._peer_routes[node_id] = raw
            self._dest_cache.pop(node_id, None)
        logger.info("learned_route node=%s dest=%s", node_id, raw)

    def guess_destination(self, node_id: str) -> Optional[str]:
        """The Waylink destination of a device we have no route for (none
        bound, or this Station just restarted): node ids end in the first 4
        hex characters of the device's destination (``pocket-1-e75a``), and
        Reticulum remembers every announce it heard. Exactly one known
        ``waypost.waylink`` destination with that prefix -> its hash; none or
        several -> None (never a guess between two devices)."""
        tail = node_id.rsplit("-", 1)[-1].lower()
        if len(tail) != 4 or any(c not in "0123456789abcdef" for c in tail):
            return None
        try:
            import RNS
        except ImportError:
            return None
        found: list[str] = []
        for dest, entry in list(getattr(RNS.Identity, "known_destinations", {}).items()):
            hexd = bytes(dest).hex()
            if not hexd.startswith(tail):
                continue
            try:
                ident = RNS.Identity(create_keys=False)
                ident.load_public_key(entry[2])
                expected = RNS.Destination.hash(ident, APP_NAME, ASPECT)
            except Exception:
                continue
            if bytes(expected) == bytes(dest):
                found.append(hexd)
        if len(found) != 1:
            return None
        logger.info("guessed_route node=%s dest=%s (from announces)", node_id, found[0])
        self.learn_route(node_id, found[0])
        return found[0]

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
            rnode=self.rnode,
        )
        apply_network(
            self.config_dir / "config",
            upstreams=parse_upstreams(os.getenv("WAYPOST_RNS_UPSTREAM", "")),
            wifi_device=os.getenv("WAYPOST_RNS_WIFI", "").strip(),
            wifi_addr=os.getenv("WAYPOST_RNS_WIFI_ADDR", "10.42.0.1").strip(),
            wifi_port=int(os.getenv("WAYPOST_RNS_WIFI_PORT", "4242")),
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
        self._destination.announce(app_data=self.announce_data())

        # "Who's there?" (roadmap D6): answer Scouts asking who's in radio
        # range, and re-announce periodically so Nearby lists keep Station.
        self._nearby_in = RNS.Destination(None, RNS.Destination.IN, RNS.Destination.PLAIN, APP_NAME, NEARBY_ASPECT)
        self._nearby_in.set_packet_callback(self._on_nearby_probe)
        self._announced_at = time.monotonic()
        self._answer_timer: Optional[threading.Timer] = None

        self._announce_handler = _OutpostAnnounceHandler(self)
        RNS.Transport.register_announce_handler(self._announce_handler)

        self._loop = asyncio.get_running_loop()
        self._running = True
        threading.Thread(target=self._reannounce_loop, name="waypost-announce", daemon=True).start()
        logger.info(
            "ReticulumTransport started node=%s hash=%s config=%s",
            self.node_id,
            self.destination_hash_hex,
            self.config_dir,
        )

    @staticmethod
    def announce_data() -> bytes:
        """Station's capability record (roadmap D6): everything, and it is Station."""
        return caps_app_data(b"", Caps(role=ROLE_STATION, services=STATION_SERVICES, station=ST_SELF))

    def _remember_peer_identity(self, dest_hex: str, identity: object) -> None:
        """Cache an identity learned from a live announce — lets the very
        next outbound packet skip Identity.recall()'s path-wait loop."""
        if identity is None:
            return
        with self._lock:
            self._peer_identities[dest_hex] = identity
            self._dest_cache.pop(dest_hex, None)

    def _on_announce(
        self,
        destination_hash: bytes,
        announced_identity: object,
        app_data: Optional[bytes],
    ) -> None:
        """RNS calls this off the asyncio thread (same as _on_packet) — marshal
        onto the event loop before touching the callback, which ends up doing
        synchronous DB writes via PairingService.auto_claim_outpost."""
        try:
            import RNS

            dest_hex = RNS.hexrep(destination_hash, delimit=False)
        except Exception:
            logger.exception("failed to read outpost announce destination hash")
            return
        self._remember_peer_identity(dest_hex, announced_identity)
        # The marker is what comes before the capability record (shared/protocol/caps.py).
        marker, _caps = split_caps(app_data)
        if not marker.startswith(AUTO_CLAIM_MARKER):
            return
        if self._destination is not None and destination_hash == self._destination.hash:
            return  # never auto-claim our own announce
        callback = self.on_unclaimed_outpost_announce
        if callback is None or self._loop is None:
            return
        try:
            rest = marker[len(AUTO_CLAIM_MARKER) :].decode("utf-8", errors="replace")
            node_id, _, display_name = rest.partition("|")
            node_id = node_id.strip()
            if not node_id:
                return
        except Exception:
            logger.exception("failed to parse outpost auto-claim announce app_data")
            return
        self._loop.call_soon_threadsafe(
            self._invoke_auto_claim, callback, node_id, dest_hex, display_name.strip() or None
        )

    @staticmethod
    def _invoke_auto_claim(
        callback: Callable[[str, str, Optional[str]], None],
        node_id: str,
        transport_dest: str,
        display_name: Optional[str],
    ) -> None:
        try:
            callback(node_id, transport_dest, display_name)
        except Exception:
            logger.exception("on_unclaimed_outpost_announce callback failed node=%s", node_id)

    def _on_packet(self, data: bytes, packet) -> None:
        if not self._running or self._loop is None:
            return
        # Logical sender lives in the Waylink envelope (env.src). RNS's
        # packet.destination_hash on an inbound packet is *this* node's IN
        # destination, not the peer's — never treat it as source.
        tp = TransportPacket(
            destination=self.node_id,
            payload=bytes(data),
            source=None,
            metadata={"encrypted": True, "transport": "reticulum"},
        )
        self._loop.call_soon_threadsafe(self._inbox.put_nowait, tp)

    # -- "who's there?" --------------------------------------------------------

    def _announce(self) -> None:
        with self._lock:
            dest = self._destination
            self._announced_at = time.monotonic()
        if dest is not None:
            dest.announce(app_data=self.announce_data())

    def _on_nearby_probe(self, data: bytes, packet: object) -> None:
        """A Scout asked who's in radio range (PLAIN waypost.nearby: one hop,
        never relayed). Answer with an announce after a random 0.3-3 s, at
        most every 30 s (firmware/scout/src/net.cpp, the Outpost the same)."""
        if not bytes(data or b"").startswith(NEARBY_PROBE):
            return
        with self._lock:
            if self._answer_timer is not None or time.monotonic() - self._announced_at < NEARBY_ANSWER_EVERY_S:
                return
            self._answer_timer = threading.Timer(0.3 + random.random() * 2.7, self._answer)
            self._answer_timer.daemon = True
            self._answer_timer.start()

    def _answer(self) -> None:
        with self._lock:
            self._answer_timer = None
        if self._running:
            self._announce()
            logger.info("answered a who's-there (nearby)")

    def _reannounce_loop(self) -> None:
        while self._running:
            time.sleep(15)
            if self._running and time.monotonic() - self._announced_at >= REANNOUNCE_S:
                self._announce()

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
                identity = self._peer_identities.get(raw)
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
            result = rns_packet.send()
            # RNS.Packet.send() returns False (no exception) when
            # Transport.outbound() can't actually place the packet on any
            # interface -- surfaced here so a silently dropped send doesn't
            # look identical to a successful one (discovered 2026-10-03
            # debugging what turned out to be a separate wire-format bug in
            # the embedded radio driver, not this -- but this check itself
            # is a real, worthwhile signal on its own).
            if result is False:
                logger.warning(
                    "rns_packet.send() returned False (not transmitted) dest=%s",
                    dest,
                )

        await asyncio.to_thread(_send)

    async def send_outpost_claim_ack(self, node_id: str, transport_dest: str) -> None:
        """Push a lightweight BOARD_SYNC-shaped ack so a freshly auto-claimed
        Outpost learns claimed=true without waiting for its own periodic
        sync — sent directly to the announce hash while the path is hot."""
        from server.services.corkboard.constants import OP_BOARD_SYNC
        from shared.protocol.envelope import (
            Envelope,
            Flags,
            SVC_CORKBOARD,
            encode_cbor,
            new_id,
        )

        dest = transport_dest.strip().lower().replace(":", "")
        env = Envelope(
            src=self.node_id,
            dst=node_id,
            svc=SVC_CORKBOARD,
            op=OP_BOARD_SYNC,
            flags=int(Flags.RESPONSE | Flags.ACK),
            mid=new_id(),
            rid=new_id(),
            payload={"ok": True, "claimed": True, "ingested": 0, "pending": []},
        )
        packet = TransportPacket(
            destination=dest,
            payload=encode_cbor(env),
            source=self.node_id,
        )
        logger.info(
            "outpost_claim_ack node=%s dest=%s",
            node_id,
            dest,
        )
        await self.send(packet)

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
            dest = self.resolve_destination(destination)
            await asyncio.to_thread(self._out_destination, dest)
            return True
        except Exception:
            return False

    async def get_route(self, destination: str) -> Optional[RouteInfo]:
        ok = await self.reachable(destination)
        if not ok:
            return None
        # Reticulum's own mesh routing (via always-on transport nodes, e.g.
        # future Outposts) resolves multi-hop paths transparently below
        # this abstraction — the app layer never sees individual RF hops,
        # only "reachable or not". Report that as a single conceptual hop
        # so callers built against MockTransport's hop-counting semantics
        # (PeerDispatchNode._is_direct_neighbor, OutpostNode._route_to_
        # station) behave the same way here: "reachable" -> "can push now".
        return RouteInfo(
            destination=destination,
            hops=1,
            next_hop=destination,
            detail={"transport": "reticulum", "encrypted": True},
        )

    async def get_link_quality(self, destination: str) -> LinkQuality:
        return LinkQuality.GOOD if await self.reachable(destination) else LinkQuality.UNKNOWN
