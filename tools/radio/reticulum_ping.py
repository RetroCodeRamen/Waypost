#!/usr/bin/env python3
"""Two-process encrypted Waylink ping over Reticulum (M2e lab).

Same-host lab uses TCP interfaces (AutoInterface cannot bind twice on one machine):

  # A — listen (TCP server)
  PYTHONUNBUFFERED=1 python -m tools.radio.reticulum_ping --role listen \\
      --config /tmp/wp-rns-a --port 37801 --tcp-port 4242

  # B — send (TCP client → A's hash)
  PYTHONUNBUFFERED=1 python -m tools.radio.reticulum_ping --role send \\
      --config /tmp/wp-rns-b --port 37811 --tcp-port 4242 --to <hash-from-A>

Expect: listener prints the payload. Traffic is Reticulum-encrypted (not clear CBOR).
Heltec USB bridge remains plaintext lab-only — see docs/security.md.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.transports.base import TransportPacket  # noqa: E402
from server.transports.reticulum import ReticulumTransport  # noqa: E402


async def listen(config: Path, port: int, tcp_port: int, wait: float) -> int:
    t = ReticulumTransport(
        config_dir=config,
        control_port=port,
        node_id="listen",
        interface="tcp_server",
        tcp_port=tcp_port,
    )
    await t.start()
    print(f"LISTEN hash={t.destination_hash_hex} config={config} tcp=:{tcp_port}")
    print(f"Waiting {wait}s for encrypted packets…", flush=True)
    deadline = time.time() + wait
    try:
        while time.time() < deadline:
            try:
                pkt = await asyncio.wait_for(t._inbox.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            body = pkt.payload.decode("utf-8", errors="replace")
            print(f"RECV encrypted payload: {body!r}", flush=True)
            if body:
                await t.stop()
                return 0
    finally:
        await t.stop()
    print("FAIL: no packet received", file=sys.stderr)
    return 1


async def send(
    config: Path, port: int, tcp_port: int, to: str, payload: str, wait: float
) -> int:
    t = ReticulumTransport(
        config_dir=config,
        control_port=port,
        node_id="send",
        interface="tcp_client",
        tcp_port=tcp_port,
    )
    await t.start()
    print(f"SEND hash={t.destination_hash_hex} → {to}", flush=True)
    await asyncio.sleep(min(3.0, wait))
    try:
        # Retry path discovery a few times
        last_exc: Exception | None = None
        for _ in range(8):
            try:
                await t.send(
                    TransportPacket(destination=to, payload=payload.encode("utf-8"))
                )
                print("sent", flush=True)
                await asyncio.sleep(1.0)
                return 0
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(1.0)
        print(f"FAIL: {last_exc}", file=sys.stderr)
        return 1
    finally:
        await t.stop()


def main() -> int:
    p = argparse.ArgumentParser(description="M2e Reticulum encrypted ping")
    p.add_argument("--role", choices=("listen", "send"), required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--port", type=int, default=37801, help="RNS instance control port")
    p.add_argument("--tcp-port", type=int, default=4242, help="TCP interface port")
    p.add_argument("--to", default="", help="Peer destination hash (send role)")
    p.add_argument("--payload", default="WAYPOST_M2E")
    p.add_argument("--wait", type=float, default=20.0)
    args = p.parse_args()

    if args.role == "listen":
        return asyncio.run(listen(args.config, args.port, args.tcp_port, args.wait))
    if not args.to:
        print("--to <hash> required for send", file=sys.stderr)
        return 2
    return asyncio.run(
        send(args.config, args.port, args.tcp_port, args.to, args.payload, args.wait)
    )


if __name__ == "__main__":
    raise SystemExit(main())
