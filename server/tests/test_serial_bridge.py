"""Serial bridge framing + device discovery tests."""

from __future__ import annotations

import struct

import pytest

from server.transports.serial_bridge import HEADER, MAGIC, SerialBridgeTransport
from tools.radio.list_devices import classify, list_radio_devices


def test_frame_header_roundtrip():
    payload = b"\xa1\x61a\x01"
    frame = HEADER.pack(MAGIC, len(payload)) + payload
    magic, length = HEADER.unpack_from(frame, 0)
    assert magic == MAGIC
    assert length == len(payload)
    assert frame[HEADER.size :] == payload


@pytest.mark.asyncio
async def test_serial_bridge_parse_injected(monkeypatch):
    """Feed bytes into the RX buffer path without real USB."""
    t = SerialBridgeTransport(device_path="/dev/null", node_id="station")
    payload = b"cbor-test-payload"
    frame = HEADER.pack(MAGIC, len(payload)) + payload

    # Simulate reader having filled buffer and drained a frame
    t._rx_buf.extend(frame)
    t._loop = __import__("asyncio").get_running_loop()
    t._running = True
    t._drain_frames()
    pkt = await t.receive_one(timeout=1.0)
    assert pkt.payload == payload
    assert pkt.destination == "station"


def test_classify_cp2102():
    assert classify({"idVendor": "10c4", "idProduct": "ea60"}) == "heltec_or_cp2102"


def test_list_devices_runs():
    # Should not throw even if no hardware in CI
    devices = list_radio_devices()
    assert isinstance(devices, list)
