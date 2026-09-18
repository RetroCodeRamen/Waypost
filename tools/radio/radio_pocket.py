"""Heltec radio Pocket — Dispatch MSG_* over USB↔LoRa bridge.

Bind still uses Station HTTP (account pairing). Chat traffic goes over the air:

  MSG_SEND / MSG_LIST  → framed CBOR on --port (peer Heltec)
  MSG_PUSH             ← framed CBOR replies from Station Heltec

Station must be running with WAYPOST_TRANSPORT=serial (or heltec) on the
other Heltec. Typical laptop setup:

  # terminal A — Station on ttyUSB0
  WAYPOST_TRANSPORT=serial WAYPOST_LORA_DEVICE=/dev/ttyUSB0 \\
    uvicorn server.api.main:app --reload --port 8000

  # terminal B — this peer on ttyUSB1
  python -m tools.radio.radio_pocket --port /dev/ttyUSB1 --user bob --peer aj

Commands: /list  /peer <user>  /help
"""

from __future__ import annotations

import argparse
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
from shared.protocol.envelope import (  # noqa: E402
    SVC_DISPATCH,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
    new_id,
)
from tools.radio.ping import read_frame, write_frame  # noqa: E402


def bind(client: httpx.Client, base: str, node_id: str, username: str) -> dict:
    r = client.post(
        f"{base}/api/dispatch/devices/bind",
        json={"node_id": node_id, "username": username},
    )
    r.raise_for_status()
    return r.json()


def login(
    client: httpx.Client,
    base: str,
    username: str,
    password: str = "waypost1",
) -> str:
    """Station account login — same credentials Pocket will use over Wi‑Fi."""
    r = client.post(
        f"{base}/api/auth/login",
        json={"username": username, "password": password},
    )
    r.raise_for_status()
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def radio_rpc(ser, env: Envelope, *, timeout: float = 8.0) -> Envelope | None:
    """Send request CBOR; wait for matching RESPONSE (by rid or mid)."""
    write_frame(ser, encode_cbor(env))
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = read_frame(ser, timeout=min(1.0, max(0.1, deadline - time.time())))
        if raw is None:
            continue
        if raw.startswith(b"WAYPOST") or raw in (b"ECHO", b"STAT"):
            continue
        try:
            reply = decode_cbor(raw)
        except Exception:
            continue
        # Unsolicited push — leave for poll_pushes / interactive drain
        if reply.op == OP_MSG_PUSH:
            continue
        if reply.rid == env.rid or (
            reply.svc == env.svc and (reply.flags & int(Flags.RESPONSE))
        ):
            return reply
    return None


def send_message(ser, *, node_id: str, sender: str, body: str, peer: str) -> Envelope | None:
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_SEND,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={
            "sender": sender,
            "body": body,
            "peer": peer,
            "transport": "lora",
        },
    )
    return radio_rpc(ser, env)


def list_messages(
    ser, *, node_id: str, peer: str, username: str
) -> Envelope | None:
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_LIST,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"peer": peer, "username": username, "limit": 20},
    )
    return radio_rpc(ser, env)


def push_listener(
    ser,
    stop: threading.Event,
    print_lock: threading.Lock,
    pending_pushes: list,
) -> None:
    """Background RX for MSG_PUSH while stdin is idle.

    Shares the serial port with the main thread via a lock on write; reads
    are coalesced carefully — interactive mode uses a shared buffer approach
    by only running listener between RPCs when --oneshot is not used.
    """
    # Interactive mode: main thread owns RX during RPC; listener only used
    # in oneshot e2e via poll_pushes. Kept as a stub for future duplex.
    _ = (ser, stop, print_lock, pending_pushes)


def poll_pushes(ser, timeout: float = 2.0) -> list[Envelope]:
    """Drain any framed envelopes for a short window (MSG_PUSH and noise)."""
    found: list[Envelope] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = read_frame(ser, timeout=min(0.4, max(0.05, deadline - time.time())))
        if raw is None:
            continue
        if raw.startswith(b"WAYPOST") or raw in (b"ECHO", b"STAT"):
            continue
        try:
            env = decode_cbor(raw)
        except Exception:
            continue
        found.append(env)
    return found


def ack_push(ser, *, node_id: str, message_id: str, timeout: float = 5.0) -> Envelope | None:
    """Confirm MSG_PUSH so Station can clear opportunistic pending."""
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_ACK,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"message_id": message_id, "state": "DELIVERED"},
    )
    return radio_rpc(ser, env, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Waypost Heltec radio Pocket (Dispatch)")
    parser.add_argument("--port", default="/dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="bob")
    parser.add_argument("--peer", default="aj")
    parser.add_argument("--node-id", default=None)
    parser.add_argument(
        "--send",
        default=None,
        help="One-shot: send this body over LoRa then exit (also --wait-push)",
    )
    parser.add_argument(
        "--wait-push",
        type=float,
        default=0.0,
        help="After --send (or alone), wait N seconds for MSG_PUSH",
    )
    parser.add_argument("--list", action="store_true", help="One-shot MSG_LIST then exit")
    parser.add_argument("--password", default="waypost1", help="Station account password")
    args = parser.parse_args()

    import serial

    node_id = args.node_id or f"radio-{args.user}"
    base = args.base.rstrip("/")
    peer = args.peer

    with httpx.Client(timeout=30.0) as client:
        try:
            client.get(f"{base}/api/health").raise_for_status()
        except Exception as exc:
            print(f"Station not reachable at {base}: {exc}", file=sys.stderr)
            return 1
        try:
            login(client, base, args.user, password=args.password)
        except Exception as exc:
            print(f"Login failed for {args.user}: {exc}", file=sys.stderr)
            return 1
        binding = bind(client, base, node_id, args.user)
        flushed = binding.get("flushed") or 0

    print(f"Radio pocket — user={args.user} node={node_id} peer={peer} port={args.port}")
    if flushed:
        print(f"Flushed {flushed} queued message(s) from while offline.")

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        time.sleep(0.3)
        ser.reset_input_buffer()

        if args.send is not None:
            reply = send_message(
                ser, node_id=node_id, sender=args.user, body=args.send, peer=peer
            )
            if reply is None:
                print("FAIL: no MSG_SEND reply over radio", file=sys.stderr)
                return 1
            payload = reply.payload or {}
            if reply.flags & int(Flags.ERROR):
                print(f"FAIL: {payload}", file=sys.stderr)
                return 1
            print(f"OK sent mid={payload.get('id')}")
            if args.wait_push > 0:
                for env in poll_pushes(ser, timeout=args.wait_push):
                    if env.op == OP_MSG_PUSH:
                        msg = (env.payload or {}).get("message") or {}
                        print(f"← PUSH {msg.get('sender')}: {msg.get('body')}")
            return 0

        if args.list:
            reply = list_messages(
                ser, node_id=node_id, peer=peer, username=args.user
            )
            if reply is None:
                print("FAIL: no MSG_LIST reply", file=sys.stderr)
                return 1
            for m in (reply.payload or {}).get("messages") or []:
                print(f"  {m.get('sender')}: {m.get('body')}  [{m.get('state')}]")
            return 0

        if args.wait_push > 0:
            for env in poll_pushes(ser, timeout=args.wait_push):
                if env.op == OP_MSG_PUSH:
                    msg = (env.payload or {}).get("message") or {}
                    print(f"← PUSH {msg.get('sender')}: {msg.get('body')}")
            return 0

        print("Commands: /list  /peer <user>  /help   (Ctrl-C to quit)")
        print("> ", end="", flush=True)
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                text = line.strip()
                if not text:
                    print("> ", end="", flush=True)
                    continue

                # Drain any pushes that arrived while idle
                for env in poll_pushes(ser, timeout=0.15):
                    if env.op == OP_MSG_PUSH:
                        msg = (env.payload or {}).get("message") or {}
                        print(f"← {msg.get('sender')}: {msg.get('body')}")

                if text.startswith("/"):
                    parts = text.split(maxsplit=1)
                    cmd = parts[0].lower()
                    arg = parts[1].strip() if len(parts) > 1 else ""
                    if cmd in ("/help", "/h"):
                        print("/list  /peer <user>  /help")
                    elif cmd == "/peer" and arg:
                        peer = arg
                        print(f"DM peer set to {peer}")
                    elif cmd == "/list":
                        reply = list_messages(
                            ser, node_id=node_id, peer=peer, username=args.user
                        )
                        if reply is None:
                            print("! no reply")
                        elif reply.flags & int(Flags.ERROR):
                            print(f"! {(reply.payload or {})}")
                        else:
                            msgs = (reply.payload or {}).get("messages") or []
                            if not msgs:
                                print("  (empty)")
                            for m in msgs:
                                print(
                                    f"  {m.get('sender')}: {m.get('body')}"
                                    f"  [{m.get('state')}]"
                                )
                    else:
                        print("Unknown command. /help")
                    print("> ", end="", flush=True)
                    continue

                reply = send_message(
                    ser, node_id=node_id, sender=args.user, body=text, peer=peer
                )
                if reply is None:
                    print("! no radio reply (is Station on the other Heltec?)")
                elif reply.flags & int(Flags.ERROR):
                    print(f"! {(reply.payload or {})}")
                else:
                    state = (reply.payload or {}).get("delivery_state")
                    print(f"✓ sent ({state or 'ok'})")
                print("> ", end="", flush=True)
        except KeyboardInterrupt:
            print("\nBye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
