"""Listen on one Heltec USB port while sending from another — air path check."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.radio.ping import read_frame, write_frame  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tx", default="/dev/ttyUSB0")
    p.add_argument("--rx", default="/dev/ttyUSB1")
    p.add_argument("--payload", default="WAYPOST_AIR_TEST")
    p.add_argument("--wait", type=float, default=4.0)
    args = p.parse_args()

    import serial

    got: list[bytes] = []
    stop = threading.Event()

    def listener() -> None:
        with serial.Serial(args.rx, 115200, timeout=0.2) as ser:
            time.sleep(0.3)
            ser.reset_input_buffer()
            deadline = time.time() + args.wait + 1
            while time.time() < deadline and not stop.is_set():
                frame = read_frame(ser, timeout=0.5)
                if frame is not None:
                    got.append(frame)
                    if frame == args.payload.encode() or frame.startswith(b"WAYPOST"):
                        stop.set()
                        return

    t = threading.Thread(target=listener, daemon=True)
    t.start()
    time.sleep(0.4)

    with serial.Serial(args.tx, 115200, timeout=0.2) as ser:
        time.sleep(0.2)
        ser.reset_input_buffer()
        payload = args.payload.encode()
        write_frame(ser, payload)
        print(f"TX {len(payload)} bytes on {args.tx}: {args.payload!r}")
        # drain local replies (errors)
        local = read_frame(ser, timeout=1.0)
        if local:
            print(f"TX-local reply: {local!r}")

    t.join(timeout=args.wait + 2)
    stop.set()

    if not got:
        print(f"FAIL: nothing received on {args.rx}")
        return 1
    print(f"RX {len(got)} frame(s) on {args.rx}:")
    for g in got:
        print(f"  {g!r}")
    if any(g == args.payload.encode() for g in got):
        print("OK air path")
        return 0
    print("FAIL: frames received but payload mismatch")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
