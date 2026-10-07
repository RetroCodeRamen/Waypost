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

# Ops that don't need a verified device: signing in (it proves the person).
UNVERIFIED_OK = {("PROFILE", "LOGIN_NONCE"), ("PROFILE", "LOGIN"), ("PROFILE", "PAIR_REDEEM")}

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
        # Belt-and-suspenders on top of _safe_handle_packet: if the loop
        # task ever ends for any other reason (receive_one itself raising,
        # a future refactor dropping the try/except), this guarantees it's
        # logged loudly instead of dying in silence the way this gateway
        # used to -- see _safe_handle_packet's docstring for the incident.
        self._task.add_done_callback(self._on_loop_done)

    def _on_loop_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "gateway_receive_loop_died transport=%s -- "
                "ALL further radio/Waylink receive processing has stopped",
                self.transport.name,
                exc_info=exc,
            )

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
                await self._safe_handle_packet(packet)
            return
        while True:
            packet = await receive_one(timeout=None)
            await self._safe_handle_packet(packet)

    async def _safe_handle_packet(self, packet: TransportPacket) -> None:
        # This loop is a long-lived fire-and-forget asyncio.Task (started in
        # start(), never awaited elsewhere) that owns the only call to
        # receive_one() -- an unhandled exception anywhere in
        # _handle_packet (decode, a handler, or send_envelope/transport.send
        # for the reply) used to kill the task outright, silently ending all
        # further radio receive processing for the rest of the process's
        # life. Worse: nothing ever surfaced it -- asyncio only logs a dead
        # task's exception when the Task object is garbage-collected, and
        # self._task is held forever in app.state, so it never was. One bad
        # packet or reply must never be able to take down the whole gateway.
        try:
            await self._handle_packet(packet)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "gateway_packet_handling_failed transport=%s dest=%s -- "
                "receive loop continuing, this packet's reply (if any) was lost",
                self.transport.name,
                packet.destination,
            )

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

        # A request that doesn't prove it comes from the device it names
        # (shared/protocol/devauth.py) is handled as from an unknown device:
        # handlers look bindings up by src, so they find none. Its reply
        # still goes to the device it named — the real one, if anyone —
        # so a genuine device that lost its key hears "not_paired" and signs
        # in again. Sign-in itself is exempt: it proves the person instead.
        original_src = None
        verify = getattr(self, "verify_src", None)
        if callable(verify) and (env.svc, env.op) not in UNVERIFIED_OK and env.src and not verify(env):
            logger.info("unverified_device src=%s svc=%s op=%s", env.src, env.svc, env.op)
            original_src = env.src
            env.src = "unverified:" + str(env.src)

        handler = self._handlers.get((env.svc, env.op))
        if handler is None and env.flags & int(Flags.RESPONSE):
            # Never answer a response — avoids error ping-pong between nodes.
            return
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

        if reply is not None and original_src is not None:
            reply.dst = original_src
        if reply is not None:
            await self.send_envelope(reply)

    async def send_envelope(self, env: Envelope) -> None:
        destination = env.dst
        # Map logical node_id → Reticulum hash when binding recorded transport_dest
        resolver = getattr(self, "_resolve_dest", None)
        if resolver is None:
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
