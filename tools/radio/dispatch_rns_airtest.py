"""M2e Dispatch-over-Reticulum airtest (TCP lab path, no RNode required).

Prerequisites:
  Terminal A — Station:
    WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=tcp_server \\
      WAYPOST_RNS_TCP_PORT=4242 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station \\
      WAYPOST_RNS_PORT=37429 \\
      uvicorn server.api.main:app --host 127.0.0.1 --port 8000

Usage:
  python -m tools.radio.dispatch_rns_airtest
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

from server.services.dispatch.constants import OP_MSG_PUSH  # noqa: E402
from server.transports.base import TransportPacket  # noqa: E402
from server.transports.reticulum import ReticulumTransport  # noqa: E402
from shared.protocol.envelope import (  # noqa: E402
    SVC_DISPATCH,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
    new_id,
)
from tools.radio.radio_pocket import login  # noqa: E402
from tools.radio.reticulum_pocket import bind, rns_rpc, station_rns_hash  # noqa: E402


async def run(args) -> int:
    base = args.base.rstrip("/")
    node_id = f"rns-{args.user}"
    token = uuid.uuid4().hex[:8]
    body = f"m2e rns {token}"

    transport = ReticulumTransport(
        config_dir=args.config,
        control_port=args.port,
        node_id=node_id,
        interface="tcp_client",
        tcp_port=args.tcp_port,
    )
    await transport.start()
    my_hash = transport.destination_hash_hex
    assert my_hash

    try:
        with httpx.Client(timeout=30.0) as client:
            client.get(f"{base}/api/health").raise_for_status()
            login(client, base, args.peer, password=args.password)
            client.post(
                f"{base}/api/dispatch/devices/bind",
                json={"node_id": "portal-aj", "username": args.peer},
            ).raise_for_status()
            login(client, base, args.user, password=args.password)
            station_hash = args.station_hash or station_rns_hash(client, base)
            if not station_hash:
                print("FAIL: Station has no rns_hash (not on reticulum?)", file=sys.stderr)
                return 1
            binding = bind(
                client, base, node_id, args.user, transport_dest=my_hash
            )
            print(f"bound {binding.get('node_id')} dest={my_hash} station={station_hash}")

        # Allow TCP link + path learn
        await asyncio.sleep(2.0)

        print(f"1) peer MSG_SEND over RNS: {body!r}")
        env = Envelope(
            src=node_id,
            dst="station",
            svc=SVC_DISPATCH,
            op="MSG_SEND",
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={"sender": args.user, "peer": args.peer, "body": body},
        )
        reply = await rns_rpc(transport, station_hash, env, timeout=15.0)
        if reply is None:
            print("FAIL: no RNS reply to MSG_SEND", file=sys.stderr)
            return 1
        if reply.flags & int(Flags.ERROR):
            print(f"FAIL: MSG_SEND error {reply.payload}", file=sys.stderr)
            return 1
        mid = (reply.payload or {}).get("id")
        print(f"   OK RNS ACK mid={mid}")

        with httpx.Client(timeout=30.0) as client:
            login(client, base, args.peer, password=args.password)
            r = client.post(
                f"{base}/api/dispatch/conversations/direct",
                json={"user_a": args.user, "user_b": args.peer},
            )
            r.raise_for_status()
            bodies = [m.get("body") for m in (r.json().get("messages") or [])]
            if body not in bodies:
                print(f"FAIL: portal history missing {body!r}", file=sys.stderr)
                return 1
            print("2) portal history contains peer message")

            reply_body = f"m2e reply {token}"
            client.post(
                f"{base}/api/dispatch/messages",
                json={
                    "sender": args.peer,
                    "peer": args.user,
                    "body": reply_body,
                    "transport": "lora",
                },
            ).raise_for_status()
            print(f"3) portal replied: {reply_body!r} — waiting MSG_PUSH…")

        deadline = time.time() + 20.0
        got_push = False
        while time.time() < deadline:
            try:
                pkt = await transport.receive_one(timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                push = decode_cbor(pkt.payload)
            except Exception:
                continue
            if push.op != OP_MSG_PUSH:
                continue
            msg = (push.payload or {}).get("message") or {}
            if msg.get("body") == reply_body:
                print(f"   OK MSG_PUSH: {msg.get('body')!r}")
                got_push = True
                break

        if not got_push:
            print("FAIL: no MSG_PUSH with portal reply", file=sys.stderr)
            return 1

        print("PASS: M2e Dispatch over Reticulum (encrypted TCP lab)")
        return 0
    finally:
        await transport.stop()


def main() -> int:
    p = argparse.ArgumentParser(description="M2e Dispatch-over-RNS airtest")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--user", default="bob")
    p.add_argument("--peer", default="aj")
    p.add_argument("--password", default="waypost1")
    p.add_argument("--config", type=Path, default=Path("/tmp/wp-rns-peer"))
    p.add_argument("--port", type=int, default=37821)
    p.add_argument("--tcp-port", type=int, default=4242)
    p.add_argument("--station-hash", default="")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
