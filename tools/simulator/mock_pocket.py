"""Interactive mock Waypost Pocket for Dispatch (no radio required).

Talks to the Station over the HTTP Waylink bridge:

  MSG_SEND / MSG_LIST  → POST /api/waylink/rpc
  pushes               ← GET  /api/waylink/outbox/{node_id}

Usage (Station already running on :8000):

    python -m tools.simulator.mock_pocket --user bob --peer aj

Commands while running:
  /list              history with current peer/room
  /peer <user>       switch DM peer
  /room <slug>       send to room:<slug> (must already be a member)
  /mail              Postbox status (includes outbox count)
  /mail list [OUTBOX|SENT|INBOX]
  /mail get <n> [folder]
  /mail send <to> <subject> | <body>
  /mail queue <to> <subject> | <body>
  /mail flush [n]
  /help
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
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
)
from server.services.mail.constants import (  # noqa: E402
    OP_MAIL_FLUSH,
    OP_MAIL_GET,
    OP_MAIL_LIST,
    OP_MAIL_NOTIFY,
    OP_MAIL_SEND,
    OP_MAIL_STATUS,
)
from shared.protocol.envelope import (  # noqa: E402
    SVC_DISPATCH,
    SVC_MAIL,
    Envelope,
    Flags,
    new_id,
)


def login(
    client: httpx.Client, base: str, username: str, password: str = "waypost1"
) -> str:
    r = client.post(
        f"{base}/api/auth/login",
        json={"username": username, "password": password},
    )
    r.raise_for_status()
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def bind(client: httpx.Client, base: str, node_id: str, username: str) -> dict:
    r = client.post(
        f"{base}/api/dispatch/devices/bind",
        json={"node_id": node_id, "username": username},
    )
    r.raise_for_status()
    return r.json()


def rpc(client: httpx.Client, base: str, env: Envelope) -> dict:
    r = client.post(f"{base}/api/waylink/rpc", json=env.to_dict())
    r.raise_for_status()
    return r.json()


def send_message(
    client: httpx.Client,
    base: str,
    *,
    node_id: str,
    sender: str,
    body: str,
    peer: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    payload: dict = {
        "sender": sender,
        "body": body,
        "transport": "lora",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    elif peer:
        payload["peer"] = peer
    else:
        raise ValueError("peer or conversation_id required")

    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_SEND,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload=payload,
    )
    return rpc(client, base, env)


def list_messages(
    client: httpx.Client,
    base: str,
    *,
    node_id: str,
    peer: str | None = None,
    conversation_id: str | None = None,
    username: str | None = None,
) -> dict:
    payload: dict = {"limit": 20}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    else:
        payload["peer"] = peer
        payload["username"] = username
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_LIST,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload=payload,
    )
    return rpc(client, base, env)


def mail_rpc(
    client: httpx.Client,
    base: str,
    *,
    node_id: str,
    op: str,
    payload: dict,
) -> dict:
    env = Envelope(
        src=node_id,
        dst="station",
        svc=SVC_MAIL,
        op=op,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload=payload,
    )
    return rpc(client, base, env)


def poll_outbox(client: httpx.Client, base: str, node_id: str) -> list[dict]:
    r = client.get(f"{base}/api/waylink/outbox/{node_id}")
    r.raise_for_status()
    return r.json().get("envelopes") or []


def outbox_loop(
    base: str,
    node_id: str,
    stop: threading.Event,
    print_lock: threading.Lock,
    token: str,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        while not stop.is_set():
            try:
                for env in poll_outbox(client, base, node_id):
                    op = env.get("op")
                    if op == OP_MSG_PUSH:
                        msg = (env.get("payload") or {}).get("message") or {}
                        conv = msg.get("conversation_id") or ""
                        with print_lock:
                            print(
                                f"\n← {msg.get('sender')}: {msg.get('body')}"
                                f"  [{msg.get('transport') or 'waylink'}]"
                                + (f" ({conv})" if conv else "")
                            )
                            print("> ", end="", flush=True)
                    elif op == OP_MAIL_NOTIFY:
                        p = env.get("payload") or {}
                        with print_lock:
                            print(
                                f"\n✉ Postbox: {p.get('unread')} unread"
                                f" ({p.get('total')} total)"
                            )
                            print("> ", end="", flush=True)
            except Exception as exc:
                with print_lock:
                    print(f"\n[outbox error] {exc}")
                    print("> ", end="", flush=True)
            stop.wait(1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Waypost Pocket (Dispatch)")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="bob")
    parser.add_argument("--peer", default="aj")
    parser.add_argument("--password", default="waypost1", help="Station account password")
    parser.add_argument("--node-id", default=None, help="Radio/node id (default pocket-<user>)")
    args = parser.parse_args()

    node_id = args.node_id or f"pocket-{args.user}"
    base = args.base.rstrip("/")
    peer = args.peer
    room_id: str | None = None
    stop = threading.Event()
    lock = threading.Lock()

    with httpx.Client(timeout=30.0) as client:
        try:
            client.get(f"{base}/api/health").raise_for_status()
        except Exception as exc:
            print(f"Station not reachable at {base}: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            token = login(client, base, args.user, password=args.password)
        except Exception as exc:
            print(f"Login failed for {args.user}: {exc}", file=sys.stderr)
            sys.exit(1)
        binding = bind(client, base, node_id, args.user)
        flushed = binding.get("flushed") or 0

    print(f"Waypost Pocket mock — user={args.user} node={node_id} peer={peer}")
    if flushed:
        print(f"Flushed {flushed} queued message(s) from while offline.")
    print("Commands: /list  /peer  /room  /dm  /mail  /help")
    print("> ", end="", flush=True)

    t = threading.Thread(
        target=outbox_loop, args=(base, node_id, stop, lock, token), daemon=True
    )
    t.start()

    try:
        with httpx.Client(
            timeout=30.0, headers={"Authorization": f"Bearer {token}"}
        ) as client:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                text = line.strip()
                if not text:
                    print("> ", end="", flush=True)
                    continue

                if text.startswith("/"):
                    parts = text.split(maxsplit=1)
                    cmd = parts[0].lower()
                    arg = parts[1].strip() if len(parts) > 1 else ""
                    with lock:
                        if cmd in ("/help", "/h"):
                            print(
                                "/list  /peer <user>  /room <slug>  /dm\n"
                                "/mail  /mail list [OUTBOX|SENT]\n"
                                "/mail get <n> [folder]\n"
                                "/mail send …  /mail queue …  /mail flush"
                            )
                        elif cmd == "/peer" and arg:
                            peer = arg
                            room_id = None
                            print(f"DM peer set to {peer}")
                        elif cmd == "/dm":
                            room_id = None
                            print(f"DM mode — peer={peer}")
                        elif cmd == "/room" and arg:
                            room_id = arg if arg.startswith("room:") else f"room:{arg}"
                            print(f"Room mode — {room_id}")
                        elif cmd == "/list":
                            try:
                                reply = list_messages(
                                    client,
                                    base,
                                    node_id=node_id,
                                    peer=None if room_id else peer,
                                    conversation_id=room_id,
                                    username=args.user,
                                )
                                payload = reply.get("payload") or {}
                                for m in payload.get("messages") or []:
                                    print(
                                        f"  {m.get('sender')}: {m.get('body')}"
                                        f"  [{m.get('state')}]"
                                    )
                                if not payload.get("messages"):
                                    print("  (empty)")
                            except Exception as exc:
                                print(f"! list failed: {exc}")
                        elif cmd == "/mail":
                            try:
                                mail_parts = arg.split(maxsplit=1)
                                sub = (mail_parts[0].lower() if mail_parts and mail_parts[0] else "status")
                                rest = mail_parts[1] if len(mail_parts) > 1 else ""
                                if sub == "status" or sub == "":
                                    reply = mail_rpc(
                                        client,
                                        base,
                                        node_id=node_id,
                                        op=OP_MAIL_STATUS,
                                        payload={"mailbox": args.user},
                                    )
                                    p = reply.get("payload") or {}
                                    print(
                                        f"  Postbox {p.get('addr')}: "
                                        f"{p.get('unread')} unread / {p.get('total')} total"
                                        f" · outbox {p.get('outbox')} · sent {p.get('sent')}"
                                    )
                                elif sub == "list":
                                    folder = (rest or "INBOX").strip().upper() or "INBOX"
                                    reply = mail_rpc(
                                        client,
                                        base,
                                        node_id=node_id,
                                        op=OP_MAIL_LIST,
                                        payload={
                                            "mailbox": args.user,
                                            "limit": 10,
                                            "folder": folder,
                                        },
                                    )
                                    for m in (reply.get("payload") or {}).get("messages") or []:
                                        flag = "*" if m.get("u") else " "
                                        who = m.get("from") if folder == "INBOX" else m.get("to")
                                        print(
                                            f"  {flag}{m.get('n'):04d}  {who}  {m.get('subj')}"
                                        )
                                elif sub == "get" and rest:
                                    bits = rest.split()
                                    n = int(bits[0])
                                    folder = bits[1].upper() if len(bits) > 1 else "INBOX"
                                    reply = mail_rpc(
                                        client,
                                        base,
                                        node_id=node_id,
                                        op=OP_MAIL_GET,
                                        payload={
                                            "mailbox": args.user,
                                            "n": n,
                                            "folder": folder,
                                        },
                                    )
                                    p = reply.get("payload") or {}
                                    if reply.get("flags", 0) & int(Flags.ERROR):
                                        print(f"! {p}")
                                    else:
                                        print(f"  From: {p.get('from')}")
                                        print(f"  Subj: {p.get('subj')}")
                                        print(f"  {p.get('body')}")
                                        if p.get("att"):
                                            att = p["att"]
                                            print(
                                                f"  Attachment: {att.get('name')} "
                                                f"({att.get('size')} B) [Wi-Fi required]"
                                            )
                                elif sub in ("send", "queue") and rest:
                                    if "|" not in rest:
                                        print("Usage: /mail send bob@waypost Subject | body text")
                                    else:
                                        head, body = rest.split("|", 1)
                                        bits = head.strip().split(maxsplit=1)
                                        to = bits[0]
                                        subj = bits[1] if len(bits) > 1 else ""
                                        reply = mail_rpc(
                                            client,
                                            base,
                                            node_id=node_id,
                                            op=OP_MAIL_SEND,
                                            payload={
                                                "mailbox": args.user,
                                                "to": to,
                                                "subject": subj,
                                                "body": body.strip(),
                                                "queue_only": sub == "queue",
                                            },
                                        )
                                        p = reply.get("payload") or {}
                                        if reply.get("flags", 0) & int(Flags.ERROR):
                                            print(f"! {p}")
                                        elif p.get("queued"):
                                            print(f"✓ queued in OUTBOX #{p.get('n')}")
                                        else:
                                            print(f"✓ mailed to {p.get('to')} (sent #{p.get('n')})")
                                elif sub == "flush":
                                    payload = {"mailbox": args.user}
                                    if rest.strip():
                                        payload["n"] = int(rest.strip())
                                    reply = mail_rpc(
                                        client,
                                        base,
                                        node_id=node_id,
                                        op=OP_MAIL_FLUSH,
                                        payload=payload,
                                    )
                                    p = reply.get("payload") or {}
                                    if reply.get("flags", 0) & int(Flags.ERROR):
                                        print(f"! {p}")
                                    else:
                                        print(f"✓ flushed {p.get('count')} outbox message(s)")
                                else:
                                    print("Usage: /mail [list|get|send|queue|flush]")
                            except Exception as exc:
                                print(f"! mail failed: {exc}")
                        else:
                            print("Unknown command. /help")
                        print("> ", end="", flush=True)
                    continue

                try:
                    reply = send_message(
                        client,
                        base,
                        node_id=node_id,
                        sender=args.user,
                        body=text,
                        peer=None if room_id else peer,
                        conversation_id=room_id,
                    )
                    payload = reply.get("payload") or {}
                    with lock:
                        if reply.get("flags", 0) & int(Flags.ERROR):
                            print(f"! error: {payload}")
                        else:
                            state = payload.get("delivery_state")
                            print(f"✓ sent ({state or 'ok'})")
                        print("> ", end="", flush=True)
                except Exception as exc:
                    with lock:
                        print(f"! send failed: {exc}")
                        print("> ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        stop.set()
        time.sleep(0.2)


if __name__ == "__main__":
    main()
