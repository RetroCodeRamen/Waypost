"""Outpost auto-claim airtest — proves ReticulumTransport's announce handler
end-to-end over a real Reticulum stack (TCP lab, or RNode LoRa).

Acts as a fake unclaimed Outpost: starts its own ReticulumTransport, then
announces under the shared (waypost, waylink) destination with the
auto-claim marker in app_data — the same shape firmware/outpost's
announce_now() sends. Then polls the Station's HTTP API to confirm it
auto-claimed the node without any pairing code.

TCP lab prerequisites:
  Terminal A — Station:
    WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=tcp_server \\
      WAYPOST_RNS_TCP_PORT=4242 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station \\
      WAYPOST_RNS_PORT=37429 WAYPOST_AUTO_CLAIM_OUTPOSTS=true \\
      uvicorn server.api.main:app --host 127.0.0.1 --port 8000

Usage:
  python -m tools.radio.auto_claim_airtest
  python -m tools.radio.auto_claim_airtest --rnode /dev/ttyUSB1   # real LoRa
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.transports.reticulum import (  # noqa: E402
    AUTO_CLAIM_MARKER,
    ReticulumTransport,
    RNodeRadio,
)
from tools.radio.radio_pocket import login  # noqa: E402


async def run(args) -> int:
    node_id = args.node_id

    if args.rnode:
        transport = ReticulumTransport(
            device_path=args.rnode,
            config_dir=args.config or Path("/tmp/wp-rns-autoclaim-rnode"),
            node_id=node_id,
            interface="rnode",
            rnode=RNodeRadio.from_env(args.rnode),
        )
    else:
        transport = ReticulumTransport(
            config_dir=args.config or Path("/tmp/wp-rns-autoclaim"),
            node_id=node_id,
            interface="tcp_client",
            tcp_port=args.tcp_port,
        )
    path_label = f"RNode LoRa {args.rnode}" if args.rnode else "TCP lab"
    await transport.start()
    my_hash = transport.destination_hash_hex
    assert my_hash
    print(f"[auto_claim_airtest] fake outpost node_id={node_id} hash={my_hash} via {path_label}")

    await asyncio.sleep(2.0)  # let the interface settle past its own start() announce
    app_data = AUTO_CLAIM_MARKER + node_id.encode("utf-8")
    transport._destination.announce(app_data=app_data)
    print(f"[auto_claim_airtest] announced with marker: {app_data!r}")

    base = args.base.rstrip("/")
    deadline = time.time() + args.timeout
    claimed_hash = None
    with httpx.Client(timeout=10.0) as client:
        client.get(f"{base}/api/health").raise_for_status()
        login(client, base, args.user, password=args.password)
        while time.time() < deadline:
            outposts = client.get(f"{base}/api/corkboard/outposts").json().get("outposts", [])
            row = next((o for o in outposts if o.get("node_id") == node_id), None)
            if row and row.get("transport_dest"):
                claimed_hash = row["transport_dest"]
                break
            await asyncio.sleep(1.0)

    await transport.stop()

    if claimed_hash and claimed_hash.lower() == my_hash.lower():
        print(f"[auto_claim_airtest] PASS — Station auto-claimed {node_id} -> {claimed_hash}")
        return 0
    if claimed_hash:
        print(
            f"[auto_claim_airtest] FAIL — claimed but hash mismatch: "
            f"expected {my_hash}, got {claimed_hash}"
        )
        return 1
    print(
        f"[auto_claim_airtest] FAIL — {node_id} was not claimed within {args.timeout}s "
        "(check WAYPOST_AUTO_CLAIM_OUTPOSTS is not disabled on Station)"
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--node-id", dest="node_id", default="airtest-outpost")
    ap.add_argument("--tcp-port", dest="tcp_port", type=int, default=4242)
    ap.add_argument("--rnode", default=None, help="serial device for a real RNode radio")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--user", default="aj")
    ap.add_argument("--password", default="waypost1")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
