"""Simulate Station + two Pocket nodes on MockTransport.

Usage (from repo root, venv active):

    python -m tools.simulator.mock_mesh
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running without install
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.gateway.waylink import WaylinkGateway
from server.transports.base import TransportPacket
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import (
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
)


async def run() -> None:
    mesh = MockMesh()
    cfg = MockTransportConfig(latency_ms_min=10, latency_ms_max=40, loss_rate=0.0, seed=1)

    station_t = mesh.attach("station", cfg)
    pocket_a = mesh.attach("pocket-a", MockTransportConfig(latency_ms_min=10, latency_ms_max=40, seed=2))
    pocket_b = mesh.attach("pocket-b", MockTransportConfig(latency_ms_min=10, latency_ms_max=40, seed=3))

    # Explicit multi-hop style links (still 1 logical hop in BFS if fully linked)
    mesh.link("pocket-a", "station")
    mesh.link("pocket-b", "station")
    mesh.link("pocket-a", "pocket-b")

    gateway = WaylinkGateway(station_t, local_id="station")
    await gateway.start()
    await pocket_a.start()
    await pocket_b.start()

    print("Mock Waylink mesh up: station, pocket-a, pocket-b")
    print("Sending PING pocket-a → station …")

    ping = Envelope(
        src="pocket-a",
        dst="station",
        svc="CORE",
        op="PING",
        flags=int(Flags.REQUEST),
        payload={"from": "pocket-a"},
    )
    await pocket_a.send(
        TransportPacket(
            destination="station",
            payload=encode_cbor(ping),
            source="pocket-a",
            message_id=ping.mid,
        )
    )

    reply = decode_cbor((await pocket_a.receive_one(timeout=3)).payload)
    print(f"Got {reply.op}: {reply.payload}")

    print("Peer ping pocket-a → pocket-b (no Station handler; raw echo not set) — reachability check")
    print("  pocket-a reachable station?", await pocket_a.reachable("station"))
    print("  pocket-a reachable pocket-b?", await pocket_a.reachable("pocket-b"))
    route = await pocket_a.get_route("station")
    print("  route to station:", route)

    await gateway.stop()
    await pocket_a.stop()
    await pocket_b.stop()
    print("Done.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
