"""Host-side radio helpers: framed serial I/O and Waylink PING over Heltec bridge."""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path
from typing import Optional

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

MAGIC = b"WP"
HEADER = struct.Struct(">2sI")


def write_frame(ser, payload: bytes) -> None:
    ser.write(HEADER.pack(MAGIC, len(payload)) + payload)
    ser.flush()


def read_frame(ser, timeout: float = 3.0) -> Optional[bytes]:
    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf.extend(chunk)
        while True:
            if len(buf) < HEADER.size:
                break
            if buf[0:2] != MAGIC:
                idx = buf.find(MAGIC)
                if idx < 0:
                    buf.clear()
                    break
                del buf[:idx]
                continue
            _magic, length = HEADER.unpack_from(buf, 0)
            if length > 65536:
                del buf[0:1]
                continue
            total = HEADER.size + length
            if len(buf) < total:
                break
            payload = bytes(buf[HEADER.size:total])
            del buf[:total]
            return payload
        time.sleep(0.02)
    return None


def cmd_echo(port: str, baud: int = 115200) -> int:
    import serial

    with serial.Serial(port, baud, timeout=0.2) as ser:
        time.sleep(0.2)
        ser.reset_input_buffer()
        write_frame(ser, b"ECHO")
        resp = read_frame(ser, timeout=2.0)
        if resp == b"ECHO":
            print(f"OK echo on {port}")
            return 0
        print(f"FAIL echo on {port}: got {resp!r}")
        return 1


def cmd_stat(port: str, baud: int = 115200) -> int:
    import serial

    with serial.Serial(port, baud, timeout=0.2) as ser:
        time.sleep(0.2)
        ser.reset_input_buffer()
        write_frame(ser, b"STAT")
        resp = read_frame(ser, timeout=2.0)
        print(resp.decode("utf-8", errors="replace") if resp else "no response")
        return 0 if resp else 1


def cmd_ping(port: str, destination: str = "peer", baud: int = 115200, wait: float = 5.0) -> int:
    import serial

    env = Envelope(
        src="station",
        dst=destination,
        svc=SVC_CORE,
        op=OP_PING,
        flags=int(Flags.REQUEST),
        payload={"t": time.time()},
    )
    with serial.Serial(port, baud, timeout=0.2) as ser:
        time.sleep(0.2)
        ser.reset_input_buffer()
        write_frame(ser, encode_cbor(env))
        print(f"PING → {destination} via {port}")
        deadline = time.time() + wait
        while time.time() < deadline:
            remaining = deadline - time.time()
            raw = read_frame(ser, timeout=min(1.0, max(0.1, remaining)))
            if raw is None:
                continue
            # Local bridge status/text replies
            if raw.startswith(b"WAYPOST"):
                print("bridge:", raw.decode("utf-8", errors="replace"))
                continue
            try:
                reply = decode_cbor(raw)
            except Exception:
                print(f"non-cbor frame ({len(raw)} bytes)")
                continue
            print(f"RX op={reply.op} src={reply.src} dst={reply.dst}")
            if reply.op == OP_PONG:
                print("OK PONG")
                return 0
        print("FAIL: no PONG (peer bridge must be up and in range)")
        return 1


def main() -> int:
    p = argparse.ArgumentParser(description="Waypost Heltec serial radio tools")
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=115200)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("echo", help="USB loopback ECHO against bridge firmware")
    sub.add_parser("stat", help="Ask bridge for STAT")
    ping = sub.add_parser("ping", help="Send Waylink PING over LoRa via bridge")
    ping.add_argument("--dst", default="peer")
    ping.add_argument("--wait", type=float, default=5.0)

    args = p.parse_args()
    if args.cmd == "echo":
        return cmd_echo(args.port, args.baud)
    if args.cmd == "stat":
        return cmd_stat(args.port, args.baud)
    if args.cmd == "ping":
        return cmd_ping(args.port, args.dst, args.baud, args.wait)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
