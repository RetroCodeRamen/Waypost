"""USB serial Waylink bridge transport — Heltec (or other) USB↔LoRa bridge firmware.

Framing (both directions):

    magic 0xWP1A (2 bytes) | uint32 BE length | CBOR envelope bytes

The Heltec firmware relays the CBOR payload over LoRa; Station speaks this framing
over /dev/waypost-lora at 115200.
"""

from __future__ import annotations

import asyncio
import struct
import threading
from collections import deque
from typing import AsyncIterator, Deque, Optional

from server.transports.base import (
    LinkQuality,
    RouteInfo,
    Transport,
    TransportPacket,
)

MAGIC = b"WP"
HEADER = struct.Struct(">2sI")  # magic + length


class SerialBridgeTransport(Transport):
    name = "serial_bridge"

    def __init__(
        self,
        device_path: str = "/dev/waypost-lora",
        *,
        baud: int = 115200,
        node_id: str = "station",
    ) -> None:
        self.device_path = device_path
        self.baud = baud
        self.node_id = node_id
        self._running = False
        self._ser = None
        self._inbox: asyncio.Queue[TransportPacket] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._rx_buf = bytearray()
        self._lock = threading.Lock()

    async def start(self) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial is required for SerialBridgeTransport") from exc

        self._ser = serial.Serial(self.device_path, self.baud, timeout=0.2)
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._reader_thread = threading.Thread(
            target=self._read_loop, name="waypost-serial-rx", daemon=True
        )
        self._reader_thread.start()

    async def stop(self) -> None:
        self._running = False
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
        self._reader_thread = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    async def send(self, packet: TransportPacket) -> None:
        if not self._running or self._ser is None:
            raise RuntimeError("SerialBridgeTransport is not started")
        frame = HEADER.pack(MAGIC, len(packet.payload)) + packet.payload
        with self._lock:
            self._ser.write(frame)
            self._ser.flush()

    def receive(self) -> AsyncIterator[TransportPacket]:
        async def _gen() -> AsyncIterator[TransportPacket]:
            while self._running:
                packet = await self._inbox.get()
                yield packet

        return _gen()

    async def receive_one(self, timeout: float | None = 2.0) -> TransportPacket:
        if timeout is None:
            return await self._inbox.get()
        return await asyncio.wait_for(self._inbox.get(), timeout=timeout)

    async def reachable(self, destination: str) -> bool:
        return self._running

    async def get_route(self, destination: str) -> Optional[RouteInfo]:
        if not self._running:
            return None
        return RouteInfo(
            destination=destination,
            hops=1,
            next_hop=destination,
            path=(self.node_id, destination),
            detail={"via": "serial_bridge", "device": self.device_path},
        )

    async def get_link_quality(self, destination: str) -> LinkQuality:
        return LinkQuality.GOOD if self._running else LinkQuality.UNKNOWN

    def _read_loop(self) -> None:
        assert self._ser is not None
        while self._running:
            try:
                chunk = self._ser.read(256)
            except Exception:
                break
            if not chunk:
                continue
            self._rx_buf.extend(chunk)
            self._drain_frames()

    def _drain_frames(self) -> None:
        while True:
            if len(self._rx_buf) < HEADER.size:
                return
            # Resync on magic
            if self._rx_buf[0:2] != MAGIC:
                idx = self._rx_buf.find(MAGIC)
                if idx < 0:
                    self._rx_buf.clear()
                    return
                del self._rx_buf[:idx]
                if len(self._rx_buf) < HEADER.size:
                    return
            magic, length = HEADER.unpack_from(self._rx_buf, 0)
            if magic != MAGIC or length > 65536:
                del self._rx_buf[0:1]
                continue
            total = HEADER.size + length
            if len(self._rx_buf) < total:
                return
            payload = bytes(self._rx_buf[HEADER.size : total])
            del self._rx_buf[:total]
            packet = TransportPacket(
                destination=self.node_id,
                payload=payload,
                source="radio",
            )
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._inbox.put_nowait, packet)


class LoopbackSerialBridge:
    """In-process pair of memory pipes for tests (no USB hardware)."""

    def __init__(self) -> None:
        self.a_to_b: Deque[bytes] = deque()
        self.b_to_a: Deque[bytes] = deque()
