"""Peer PONG helper — listen on a Heltec USB bridge and reply to Waylink PINGs over LoRa."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.protocol.envelope import (  # noqa: E402
    OP_PING,
    OP_PONG,
    SVC_CORE,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
)
from tools.radio.ping import read_frame, write_frame  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Waypost LoRa PONG peer on Heltec USB bridge")
    p.add_argument("--port", default="/dev/ttyUSB1")
    p.add_argument("--id", default="peer")
    p.add_argument("--seconds", type=float, default=30.0)
    args = p.parse_args()

    import serial

    print(f"PONG peer id={args.id} on {args.port} for {args.seconds}s")
    with serial.Serial(args.port, 115200, timeout=0.2) as ser:
        time.sleep(0.3)
        ser.reset_input_buffer()
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            raw = read_frame(ser, timeout=0.5)
            if raw is None:
                continue
            if raw.startswith(b"WAYPOST") or raw in (b"ECHO", b"STAT"):
                continue
            try:
                env = decode_cbor(raw)
            except Exception:
                print(f"skip non-cbor {len(raw)}b")
                continue
            print(f"RX {env.svc}/{env.op} from {env.src}")
            if env.svc == SVC_CORE and env.op == OP_PING:
                reply = env.make_response(
                    op=OP_PONG,
                    payload={"echo": env.payload, "peer": args.id},
                    flags=Flags.RESPONSE,
                )
                reply.src = args.id
                reply.dst = env.src or "station"
                write_frame(ser, encode_cbor(reply))
                print(f"TX PONG → {reply.dst}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
