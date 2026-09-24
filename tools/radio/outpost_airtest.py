"""OutpostNode airtest — real RNode LoRa, Outpost directly adjacent to Station.

First hardware exercise of OutpostNode (M6, sim-first until now): with only
two RNode-flashed Heltec V3 boards on hand, this tests the single-hop case
(Outpost -> Station directly) rather than a multi-hop chain — that needs a
third radio. It still proves the real thing sim couldn't: OutpostNode's
routing (`_route_to_station`) and its Station-dialect final hop
(`_deliver_to_station`, added when a sim test caught the peer-relay-vs-
Station-RPC envelope mismatch) both work over actual encrypted RF, not just
MockMesh.

Prerequisites:
  Terminal A — Station on its own RNode-flashed board:
    WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=rnode \\
      WAYPOST_LORA_DEVICE=/dev/ttyUSB0 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station-rnode \\
      uvicorn server.api.main:app --host 127.0.0.1 --port 8000

Usage:
  python -m tools.radio.outpost_airtest --rnode /dev/ttyUSB1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sqlite3  # noqa: E402

from server.services.dispatch.outpost import OutpostNode  # noqa: E402
from server.services.dispatch.store import DispatchStore  # noqa: E402
from server.transports.reticulum import ReticulumTransport, RNodeRadio  # noqa: E402
from tools.radio.radio_pocket import login  # noqa: E402
from tools.radio.reticulum_pocket import bind, station_rns_hash  # noqa: E402


def _store() -> DispatchStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return DispatchStore(conn)


async def run(args) -> int:
    base = args.base.rstrip("/")
    node_id = f"outpost-{uuid.uuid4().hex[:6]}"
    token = uuid.uuid4().hex[:8]
    body = f"outpost airtest {token}"

    transport = ReticulumTransport(
        device_path=args.rnode,
        config_dir=args.config or Path("/tmp/wp-rns-outpost-rnode"),
        control_port=args.port,
        node_id=node_id,
        interface="rnode",
        rnode=RNodeRadio.from_env(args.rnode),
    )
    outpost = OutpostNode(node_id=node_id, transport=transport, store=_store())
    await outpost.start()
    my_hash = transport.destination_hash_hex
    assert my_hash

    with httpx.Client(timeout=30.0) as client:
        client.get(f"{base}/api/health").raise_for_status()
        login(client, base, args.user, password=args.password)
        station_hash = args.station_hash or station_rns_hash(client, base)
        if not station_hash:
            print("FAIL: Station has no rns_hash (not on reticulum?)", file=sys.stderr)
            return 1
        # No Outpost registry exists yet (that's real scope of its own —
        # see the Corkboard discussion in AGENT_HANDOFF.md). Borrowing the
        # device-bind endpoint is a lab-only shortcut to get Station's own
        # transport.learn_route(node_id, hash) called, so its reply can
        # find its way back to this Outpost over RF. bind_device only lets
        # a session bind under its own username, so this rides along on
        # --user rather than a dedicated identity.
        bind(client, base, node_id, args.user, transport_dest=my_hash)
    print(f"1) station RNS hash: {station_hash}")

    transport.learn_route(outpost.station_node_id, station_hash)
    print(f"2) outpost {node_id} on {args.rnode} (dest {my_hash}), routes learned both ways")

    try:
        await asyncio.sleep(5.0)  # let the RNode path settle / RNS discover it

        seed_msg, _ = outpost.store.add_message(
            conversation_id="test:seed",
            sender=args.peer,
            body=body,
            delivery_state="SENT",
        )
        outpost.store.queue_courier(seed_msg["id"], "station", for_user=args.user)
        print(f"3) seeded courier item, relaying toward station: {body!r}")

        next_hop = await outpost._route_to_station()
        print(f"   route_to_station -> {next_hop}")
        if next_hop != "station":
            print(f"FAIL: expected direct route to station, got {next_hop!r}", file=sys.stderr)
            return 1

        relayed = await outpost.relay_toward_station()
        if relayed != 1:
            print(f"FAIL: relay_toward_station returned {relayed}, expected 1", file=sys.stderr)
            return 1
        print("   OK relayed over RNode LoRa")

        with httpx.Client(timeout=30.0) as client:
            login(client, base, args.user, password=args.password)
            r = client.post(
                f"{base}/api/dispatch/conversations/direct",
                json={"user_a": args.peer, "user_b": args.user},
            )
            r.raise_for_status()
            bodies = [m.get("body") for m in (r.json().get("messages") or [])]
            if body not in bodies:
                print(f"FAIL: portal history missing {body!r}", file=sys.stderr)
                return 1
            print("4) portal history contains the relayed message")

        print("PASS: OutpostNode relay over real RNode LoRa (single hop)")
        return 0
    finally:
        await outpost.stop()


def main() -> int:
    p = argparse.ArgumentParser(description="OutpostNode airtest over RNode LoRa")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--user", default="aj", help="Station account the relayed message is addressed to")
    p.add_argument("--peer", default="bob", help="Sender name on the relayed message")
    p.add_argument("--password", default="waypost1")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--port", type=int, default=37831)
    p.add_argument("--rnode", required=True, help="Serial port of the Outpost's RNode board, e.g. /dev/ttyUSB1")
    p.add_argument("--station-hash", default="")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
