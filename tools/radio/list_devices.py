"""List USB serial devices that look like Waypost LoRa radios (Heltec / RNode)."""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any


CP210X = ("10c4", "ea60")
CH340 = ("1a86", "7523")


def _read_uevent(tty: str) -> dict[str, str]:
    # Walk sysfs for idVendor/idProduct when available
    out: dict[str, str] = {}
    name = Path(tty).name
    sys = Path("/sys/class/tty") / name / "device"
    if not sys.exists():
        return out
    try:
        start = sys.resolve()
    except OSError:
        start = sys
    for parent in [start, *start.parents]:
        vendor = parent / "idVendor"
        product = parent / "idProduct"
        if vendor.is_file() and product.is_file():
            out["idVendor"] = vendor.read_text().strip()
            out["idProduct"] = product.read_text().strip()
            serial = parent / "serial"
            if serial.is_file():
                out["serial"] = serial.read_text().strip()
            manuf = parent / "manufacturer"
            if manuf.is_file():
                out["manufacturer"] = manuf.read_text().strip()
            product_name = parent / "product"
            if product_name.is_file():
                out["product"] = product_name.read_text().strip()
            break
    return out


def _aliases_for(dev: str) -> list[str]:
    aliases: list[str] = []
    for base in (Path("/dev/serial/by-path"), Path("/dev/serial/by-id"), Path("/dev")):
        if not base.is_dir():
            continue
        for p in base.iterdir():
            try:
                if p.is_symlink() and os.path.realpath(p) == os.path.realpath(dev):
                    aliases.append(str(p))
            except OSError:
                continue
    # Prefer waypost-* names first
    aliases.sort(key=lambda a: (0 if "waypost" in a else 1, a))
    return aliases


def classify(info: dict[str, str]) -> str:
    vid = (info.get("idVendor") or "").lower()
    pid = (info.get("idProduct") or "").lower()
    if (vid, pid) == CP210X:
        return "heltec_or_cp2102"
    if (vid, pid) == CH340:
        return "ch340_possible_rnode"
    if vid or pid:
        return "usb_serial"
    return "unknown"


def list_radio_devices() -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = sorted(
        set(glob.glob("/dev/ttyUSB*"))
        | set(glob.glob("/dev/ttyACM*"))
        | set(glob.glob("/dev/waypost-lora*"))
    )
    for path in candidates:
        real = os.path.realpath(path)
        if real in seen and path.startswith("/dev/waypost"):
            # Still record alias-only entries attached to known tty
            pass
        info = _read_uevent(real if real.startswith("/dev/tty") else path)
        if path.startswith("/dev/waypost"):
            # Resolve to underlying tty for metadata
            info = _read_uevent(real) or info
        key = real
        if key in seen and not path.startswith("/dev/waypost"):
            continue
        if not path.startswith("/dev/waypost"):
            seen.add(key)
        kind = classify(info)
        if kind == "unknown" and not path.startswith("/dev/waypost"):
            # Skip non-USB oddities
            if not info.get("idVendor"):
                continue
        devices.append(
            {
                "path": path,
                "realpath": real,
                "kind": kind,
                "vid": info.get("idVendor"),
                "pid": info.get("idProduct"),
                "serial": info.get("serial"),
                "manufacturer": info.get("manufacturer"),
                "product": info.get("product"),
                "aliases": _aliases_for(real),
                "accessible": os.access(path, os.R_OK | os.W_OK),
            }
        )
    # Deduplicate by realpath keeping richest entry
    by_real: dict[str, dict[str, Any]] = {}
    for d in devices:
        prev = by_real.get(d["realpath"])
        if prev is None or d["path"].startswith("/dev/waypost"):
            if prev and d["path"].startswith("/dev/waypost"):
                # merge: keep tty path as realpath entry, note alias
                prev.setdefault("waypost_aliases", []).append(d["path"])
                by_real[d["realpath"]] = prev
            else:
                by_real[d["realpath"]] = d
        elif prev:
            aliases = sorted(set(prev.get("aliases", []) + d.get("aliases", [])))
            prev["aliases"] = aliases
    return sorted(by_real.values(), key=lambda d: d["path"])


def probe_open(path: str, baud: int = 115200) -> dict[str, Any]:
    try:
        import serial  # type: ignore
    except ImportError:
        return {"ok": False, "error": "pyserial not installed"}
    try:
        with serial.Serial(path, baud, timeout=0.3) as ser:
            pending = ser.read(256)
        return {"ok": True, "bytes_waiting": len(pending)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main() -> int:
    devices = list_radio_devices()
    if not devices:
        print("No USB serial radio candidates found.")
        print("Plug in Heltec (CP2102) boards and check dialout group membership.")
        return 1
    print(f"Found {len(devices)} serial radio candidate(s):\n")
    for d in devices:
        print(f"  {d['path']}")
        print(f"    realpath: {d['realpath']}")
        print(f"    kind:     {d['kind']}")
        print(f"    usb:      {d.get('vid')}:{d.get('pid')} serial={d.get('serial')}")
        print(f"    product:  {d.get('product')}")
        print(f"    access:   {'rw' if d['accessible'] else 'NO (dialout?)'}")
        if d.get("aliases"):
            print(f"    aliases:  {', '.join(d['aliases'][:4])}")
        probe = probe_open(d["path"])
        print(f"    probe:    {probe}")
        print()
    waypost = [d for d in devices if any("waypost-lora" in a for a in d.get("aliases", []))]
    if not waypost:
        print("Tip: install udev rules from deploy/raspberry-pi/udev/99-waypost-lora.rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
