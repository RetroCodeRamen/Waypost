"""Encrypted Dispatch Pocket over Reticulum (M2e lab).

Bind still uses Station HTTP (account + transport_dest). Chat CBOR goes over
encrypted Reticulum (TCP lab path or AutoInterface / RNode in production).

  # Terminal A — Station as RNS TCP server
  WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=tcp_server \\
    WAYPOST_RNS_TCP_PORT=4242 WAYPOST_RNS_CONFIG=data/reticulum-station \\
    uvicorn server.api.main:app --host 127.0.0.1 --port 8000

  # Terminal B — this peer
  python -m tools.radio.reticulum_pocket --user bob --peer aj \\
      --config /tmp/wp-rns-pocket --port 37811 --tcp-port 4242 \\
      --station-hash <from GET /api/signal → waylink.rns_hash>

Commands: /list  /peer <user>  /help
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.services.dispatch.constants import (  # noqa: E402
    OP_MSG_ACK,
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
)
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


def bind(
    client: httpx.Client,
    base: str,
    node_id: str,
    username: str,
    *,
    transport_dest: str,
) -> dict:
    r = client.post(
        f"{base}/api/dispatch/devices/bind",
        json={
            "node_id": node_id,
            "username": username,
            "transport_dest": transport_dest,
        },
    )
    r.raise_for_status()
    return r.json()


def station_rns_hash(client: httpx.Client, base: str) -> str | None:
    r = client.get(f"{base}/api/signal")
    r.raise_for_status()
    return (r.json().get("waylink") or {}).get("rns_hash")


async def rns_rpc(
    transport: ReticulumTransport,
    station_hash: str,
    env: Envelope,
    *,
    timeout: float = 12.0,
) -> Envelope | None:
    await transport.send(
        TransportPacket(destination=station_hash, payload=encode_cbor(env))
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        try:
            pkt = await transport.receive_one(timeout=min(1.0, remaining))
        except asyncio.TimeoutError:
            continue
        try:
            reply = decode_cbor(pkt.payload)
        except Exception:
            continue
        if reply.op == OP_MSG_PUSH:
            # Ignore unsolicited pushes while waiting for RPC reply
            continue
        if reply.rid == env.rid or (
            reply.svc == env.svc and (reply.flags & int(Flags.RESPONSE))
        ):
            return reply
    return None


async def send_message(
    transport: ReticulumTransport,
    *,
    station_hash: str,
    node_id: str,
    sender: str,
    body: str,
    peer: str,
) -> Envelope | None:
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_SEND,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"sender": sender, "peer": peer, "body": body},
    )
    return await rns_rpc(transport, station_hash, env)


async def list_messages(
    transport: ReticulumTransport,
    *,
    station_hash: str,
    node_id: str,
    peer: str,
) -> Envelope | None:
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_LIST,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"peer": peer},
    )
    return await rns_rpc(transport, station_hash, env)


async def drain_pushes(
    transport: ReticulumTransport,
    stop: threading.Event,
    print_lock: threading.Lock,
    node_id: str,
    station_hash: str,
) -> None:
    while not stop.is_set():
        try:
            pkt = await transport.receive_one(timeout=0.5)
        except asyncio.TimeoutError:
            continue
        except Exception:
            await asyncio.sleep(0.5)
            continue
        try:
            env = decode_cbor(pkt.payload)
        except Exception:
            continue
        if env.op != OP_MSG_PUSH:
            # not ours — drop or ignore
            continue
        msg = (env.payload or {}).get("message") or {}
        with print_lock:
            print(
                f"\n← {msg.get('sender')}: {msg.get('body')}"
                f"  [rns/{msg.get('transport') or 'encrypted'}]"
            )
            print("> ", end="", flush=True)
        # ACK so Station can clear pending
        mid = msg.get("id")
        if mid:
            ack = Envelope(
                src=node_id,
                dst="station",
                svc=SVC_DISPATCH,
                op=OP_MSG_ACK,
                flags=int(Flags.REQUEST),
                mid=new_id(),
                payload={"message_id": mid, "state": "DELIVERED"},
            )
            try:
                await transport.send(
                    TransportPacket(destination=station_hash, payload=encode_cbor(ack))
                )
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Reticulum Waypost Pocket (Dispatch)")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="bob")
    parser.add_argument("--peer", default="aj")
    parser.add_argument("--password", default="waypost1")
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--config", type=Path, default=Path("/tmp/wp-rns-pocket"))
    parser.add_argument("--port", type=int, default=37811)
    parser.add_argument("--tcp-port", type=int, default=4242)
    parser.add_argument(
        "--station-hash",
        default="",
        help="Station RNS hash (default: from GET /api/signal)",
    )
    args = parser.parse_args()

    node_id = args.node_id or f"rns-{args.user}"
    base = args.base.rstrip("/")
    peer = args.peer

    async def run() -> int:
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

        with httpx.Client(timeout=30.0) as client:
            try:
                client.get(f"{base}/api/health").raise_for_status()
            except Exception as exc:
                print(f"Station not reachable at {base}: {exc}", file=sys.stderr)
                await transport.stop()
                return 1
            try:
                login(client, base, args.user, password=args.password)
            except Exception as exc:
                print(f"Login failed: {exc}", file=sys.stderr)
                await transport.stop()
                return 1
            station_hash = args.station_hash or station_rns_hash(client, base)
            if not station_hash:
                print(
                    "No station RNS hash — is WAYPOST_TRANSPORT=reticulum?",
                    file=sys.stderr,
                )
                await transport.stop()
                return 1
            binding = bind(
                client, base, node_id, args.user, transport_dest=my_hash
            )
            flushed = binding.get("flushed") or 0

        print(
            f"RNS pocket — user={args.user} node={node_id} "
            f"hash={my_hash} station={station_hash}"
        )
        if flushed:
            print(f"Flushed {flushed} queued message(s).")
        print("Commands: /list  /peer <user>  /help")
        print("> ", end="", flush=True)

        stop = threading.Event()
        lock = threading.Lock()
        drain_task = asyncio.create_task(
            drain_pushes(transport, stop, lock, node_id, station_hash)
        )

        nonlocal_peer = peer
        try:
            loop = asyncio.get_running_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                line = line.strip()
                if not line:
                    print("> ", end="", flush=True)
                    continue
                if line in ("/help", "help"):
                    print("  /list  /peer <user>  /help  or type a message")
                elif line.startswith("/peer "):
                    nonlocal_peer = line.split(None, 1)[1].strip()
                    print(f"peer={nonlocal_peer}")
                elif line == "/list":
                    reply = await list_messages(
                        transport,
                        station_hash=station_hash,
                        node_id=node_id,
                        peer=nonlocal_peer,
                    )
                    if reply is None:
                        print("! no reply")
                    elif reply.flags & int(Flags.ERROR):
                        print(f"! {reply.payload}")
                    else:
                        for m in (reply.payload or {}).get("messages") or []:
                            print(f"  {m.get('sender')}: {m.get('body')}")
                else:
                    reply = await send_message(
                        transport,
                        station_hash=station_hash,
                        node_id=node_id,
                        sender=args.user,
                        body=line,
                        peer=nonlocal_peer,
                    )
                    if reply is None:
                        print("! no ACK")
                    elif reply.flags & int(Flags.ERROR):
                        print(f"! {reply.payload}")
                    else:
                        print(f"✓ {(reply.payload or {}).get('id')}")
                print("> ", end="", flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            drain_task.cancel()
            await transport.stop()
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
