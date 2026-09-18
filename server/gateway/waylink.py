"""Waylink gateway — maps envelopes onto a Transport."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional

from server.transports.base import Transport, TransportPacket
from shared.protocol.envelope import (
    OP_PING,
    OP_PONG,
    SVC_CORE,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
)

logger = logging.getLogger("waypost.gateway")

Handler = Callable[[Envelope], Awaitable[Optional[Envelope]]]


class WaylinkGateway:
    """Receives Waylink packets, dispatches to service handlers, sends replies."""

    def __init__(self, transport: Transport, local_id: str = "station") -> None:
        self.transport = transport
        self.local_id = local_id
        self._handlers: Dict[tuple[str, str], Handler] = {}
        self._seen_mids: set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self.register(SVC_CORE, OP_PING, self._handle_ping)

    def register(self, service: str, operation: str, handler: Handler) -> None:
        self._handlers[(service, operation)] = handler

    async def _handle_ping(self, env: Envelope) -> Envelope:
        return env.make_response(op=OP_PONG, payload={"echo": env.payload})

    async def start(self) -> None:
        await self.transport.start()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.transport.stop()

    async def _loop(self) -> None:
        receive_one = getattr(self.transport, "receive_one", None)
        if receive_one is None:
            async for packet in self.transport.receive():
                await self._handle_packet(packet)
            return
        while True:
            packet = await receive_one(timeout=None)
            await self._handle_packet(packet)

    async def _handle_packet(self, packet: TransportPacket) -> None:
        try:
            env = decode_cbor(packet.payload)
        except Exception:
            logger.warning(
                "malformed_packet transport=%s dest=%s",
                self.transport.name,
                packet.destination,
            )
            return

        if env.mid in self._seen_mids:
            logger.info(
                "duplicate_suppressed mid=%s svc=%s op=%s transport=%s",
                env.mid,
                env.svc,
                env.op,
                self.transport.name,
            )
            return
        self._seen_mids.add(env.mid)
        if len(self._seen_mids) > 4096:
            self._seen_mids = set(list(self._seen_mids)[-2048:])

        logger.info(
            "rpc_received mid=%s rid=%s svc=%s op=%s src=%s dst=%s transport=%s",
            env.mid,
            env.rid,
            env.svc,
            env.op,
            env.src,
            env.dst,
            self.transport.name,
        )

        handler = self._handlers.get((env.svc, env.op))
        if handler is None:
            reply = env.make_response(
                op=env.op,
                payload={"error": "unknown_operation", "svc": env.svc, "op": env.op},
                error=True,
            )
        else:
            result = handler(env)
            if asyncio.iscoroutine(result):
                reply = await result
            else:
                reply = result

        if reply is not None:
            await self.send_envelope(reply)

    async def send_envelope(self, env: Envelope) -> None:
        destination = env.dst
        # Map logical node_id → Reticulum hash when binding recorded transport_dest
        resolver = getattr(self, "_resolve_dest", None)
        if resolver is None and hasattr(self.transport, "resolve_destination"):
            resolver = self.transport.resolve_destination
        if callable(resolver):
            try:
                destination = resolver(destination) or destination
            except Exception:
                logger.exception("dest_resolve_failed dst=%s", env.dst)
        payload = encode_cbor(env)
        packet = TransportPacket(
            destination=destination,
            payload=payload,
            source=env.src or self.local_id,
            message_id=env.mid,
            ttl=env.ttl,
        )
        logger.info(
            "rpc_send mid=%s rid=%s svc=%s op=%s src=%s dst=%s transport=%s",
            env.mid,
            env.rid,
            env.svc,
            env.op,
            packet.source,
            packet.destination,
            self.transport.name,
        )
        await self.transport.send(packet)

    async def ping(self, destination: str, payload: Optional[dict] = None) -> None:
        env = Envelope(
            src=self.local_id,
            dst=destination,
            svc=SVC_CORE,
            op=OP_PING,
            flags=int(Flags.REQUEST),
            payload=payload or {},
        )
        await self.send_envelope(env)
