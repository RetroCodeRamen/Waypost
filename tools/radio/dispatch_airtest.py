"""Dispatch Heltec air tests — M2c bidirectional + N1 appear-later.

Prerequisites:
  - Two Heltec V3 bridges on /dev/ttyUSB0 (Station) and /dev/ttyUSB1 (peer)
  - Station:
      WAYPOST_TRANSPORT=serial WAYPOST_LORA_DEVICE=/dev/ttyUSB0 \\
        uvicorn server.api.main:app --host 127.0.0.1 --port 8000

Usage:
  python -m tools.radio.dispatch_airtest              # M2c online path
  python -m tools.radio.dispatch_airtest --appear-later  # N1 opportunistic
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.services.dispatch.constants import OP_MSG_PUSH  # noqa: E402
from shared.protocol.envelope import Flags  # noqa: E402
from tools.radio.radio_pocket import (  # noqa: E402
    ack_push,
    bind,
    list_messages,
    login,
    poll_pushes,
    send_message,
)


def run_m2c(args) -> int:
    import serial

    base = args.base.rstrip("/")
    node_id = f"radio-{args.user}"
    token = uuid.uuid4().hex[:8]
    body = f"m2c air {token}"

    with httpx.Client(timeout=30.0) as client:
        client.get(f"{base}/api/health").raise_for_status()
        login(client, base, args.peer, password=args.password)
        client.post(
            f"{base}/api/dispatch/devices/bind",
            json={"node_id": "portal-aj", "username": args.peer},
        ).raise_for_status()
        login(client, base, args.user, password=args.password)
        binding = bind(client, base, node_id, args.user)
        print(f"bound {binding.get('node_id') or node_id} → {args.user}")

    print(f"1) peer MSG_SEND over {args.peer_port}: {body!r}")
    with serial.Serial(args.peer_port, args.baud, timeout=0.2) as ser:
        time.sleep(0.3)
        ser.reset_input_buffer()
        reply = send_message(
            ser,
            node_id=node_id,
            sender=args.user,
            body=body,
            peer=args.peer,
        )
        if reply is None:
            print("FAIL: no radio reply to MSG_SEND", file=sys.stderr)
            return 1
        if reply.flags & int(Flags.ERROR):
            print(f"FAIL: MSG_SEND error {reply.payload}", file=sys.stderr)
            return 1
        mid = (reply.payload or {}).get("id")
        print(f"   OK radio ACK mid={mid}")

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

            reply_body = f"m2c reply {token}"
            client.post(
                f"{base}/api/dispatch/messages",
                json={
                    "sender": args.peer,
                    "peer": args.user,
                    "body": reply_body,
                    "transport": "lora",
                },
            ).raise_for_status()
            print(f"3) portal reply queued: {reply_body!r}")

        print("4) waiting for MSG_PUSH on peer Heltec…")
        got = False
        deadline = time.time() + 12.0
        while time.time() < deadline and not got:
            for env in poll_pushes(ser, timeout=1.5):
                if env.op != OP_MSG_PUSH:
                    continue
                msg = (env.payload or {}).get("message") or {}
                print(f"   RX PUSH {msg.get('sender')}: {msg.get('body')}")
                if msg.get("body") == reply_body:
                    mid = msg.get("id")
                    if mid:
                        ack_push(ser, node_id=node_id, message_id=str(mid))
                    got = True
                    break
        if not got:
            print("FAIL: no MSG_PUSH with portal reply over radio", file=sys.stderr)
            return 1

        listed = list_messages(
            ser, node_id=node_id, peer=args.peer, username=args.user
        )
        if listed and not (listed.flags & int(Flags.ERROR)):
            n = len((listed.payload or {}).get("messages") or [])
            print(f"5) MSG_LIST over radio returned {n} message(s)")

    print("PASS: M2c Dispatch over Heltec")
    return 0


def run_appear_later(args) -> int:
    """N1: portal queues while peer unbound; bind → LoRa MSG_PUSH without resend."""
    import serial

    base = args.base.rstrip("/")
    node_id = f"radio-{args.user}"
    token = uuid.uuid4().hex[:8]
    body = f"n1 appear {token}"

    with httpx.Client(timeout=30.0) as client:
        client.get(f"{base}/api/health").raise_for_status()
        login(client, base, args.user, password=args.password)
        client.post(
            f"{base}/api/dispatch/devices/unbind",
            json={"username": args.user},
        ).raise_for_status()
        login(client, base, args.peer, password=args.password)
        client.post(
            f"{base}/api/dispatch/devices/bind",
            json={"node_id": "portal-aj", "username": args.peer},
        ).raise_for_status()

        sent = client.post(
            f"{base}/api/dispatch/messages",
            json={
                "sender": args.peer,
                "peer": args.user,
                "body": body,
                "transport": "lora",
            },
        )
        sent.raise_for_status()
        state = sent.json()["message"]["delivery_state"]
        mid = sent.json()["message"]["id"]
        if state != "QUEUED":
            print(f"FAIL: expected QUEUED got {state}", file=sys.stderr)
            return 1
        print(f"1) portal queued while {args.user} unbound: {body!r} ({state})")

        sync = client.get(f"{base}/api/signal").json().get("sync") or {}
        pending = sync.get("pending_dispatch") or 0
        if pending < 1:
            print(f"FAIL: Signal sync.pending_dispatch={pending}", file=sys.stderr)
            return 1
        print(f"2) Signal shows {pending} Dispatch waiting")

        print(f"3) bind {node_id} + wait for LoRa MSG_PUSH…")
        with serial.Serial(args.peer_port, args.baud, timeout=0.2) as ser:
            time.sleep(0.3)
            ser.reset_input_buffer()
            login(client, base, args.user, password=args.password)
            binding = bind(client, base, node_id, args.user)
            flushed = binding.get("flushed") or 0
            print(f"   flushed={flushed}")
            if flushed < 1:
                print("FAIL: bind did not flush pending", file=sys.stderr)
                return 1

            got = False
            deadline = time.time() + 12.0
            while time.time() < deadline and not got:
                for env in poll_pushes(ser, timeout=1.5):
                    if env.op != OP_MSG_PUSH:
                        continue
                    msg = (env.payload or {}).get("message") or {}
                    print(f"   RX PUSH {msg.get('sender')}: {msg.get('body')}")
                    if msg.get("body") == body or msg.get("id") == mid:
                        ack = ack_push(
                            ser, node_id=node_id, message_id=str(msg.get("id") or mid)
                        )
                        if ack is None or (ack.flags & int(Flags.ERROR)):
                            print(f"WARN: MSG_ACK weak: {ack}", file=sys.stderr)
                        got = True
                        break
            if not got:
                print("FAIL: no MSG_PUSH after appear", file=sys.stderr)
                return 1

        sync2 = client.get(f"{base}/api/signal").json().get("sync") or {}
        by_user = sync2.get("pending_by_user") or {}
        if by_user.get(args.user):
            print(
                f"FAIL: still pending for {args.user}: {by_user}",
                file=sys.stderr,
            )
            return 1
        print("4) pending cleared after ACK")

    print("PASS: N1 opportunistic Dispatch (appear-later)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Dispatch over Heltec E2E air test")
    p.add_argument("--station-port", default="/dev/ttyUSB0", help="(info only)")
    p.add_argument("--peer-port", default="/dev/ttyUSB1")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--user", default="bob")
    p.add_argument("--peer", default="aj")
    p.add_argument("--password", default="waypost1", help="Station account password")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument(
        "--appear-later",
        action="store_true",
        help="N1: queue while unbound, deliver on bind over LoRa",
    )
    args = p.parse_args()

    try:
        with httpx.Client(timeout=5.0) as client:
            client.get(f"{args.base.rstrip('/')}/api/health").raise_for_status()
    except Exception as exc:
        print(f"FAIL: Station not at {args.base}: {exc}", file=sys.stderr)
        return 1

    if args.appear_later:
        return run_appear_later(args)
    return run_m2c(args)


if __name__ == "__main__":
    raise SystemExit(main())
