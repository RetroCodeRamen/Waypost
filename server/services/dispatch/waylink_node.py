"""WaylinkPeerNode — shared transport/request-response plumbing for nodes
that both accept unsolicited requests and issue their own correlated
requests on the same transport.

Station's WaylinkGateway (server/gateway/waylink.py) only ever replies to
requests, never awaits a reply itself, so it can dispatch inbound packets
purely by (svc, op). A Pocket or an Outpost is different: it must also
issue its own requests (MSG_SYNC, a relay push) and await a correlated
reply on the *same* transport, so a reply envelope must never be misread
as a new inbound request just because this node also handles that op.
This class checks Flags.RESPONSE + rid first, before touching the handler
table, which is what makes that safe — it never touches WaylinkGateway or
Station's behavior.

Extracted from PeerDispatchNode (M3) when OutpostNode needed the identical
mechanism; see docs/architecture.md's Pocket<->Pocket section and
docs/offline-sync.md for the design this serves.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional

from server.transports.base import Transport, TransportPacket
from shared.protocol.envelope import Envelope, Flags, decode_cbor, encode_cbor

logger = logging.getLogger("waypost.dispatch.waylink_node")

Handler = Callable[[Envelope], Awaitable[Optional[Envelope]]]


class WaylinkPeerNode:
    """Base class: transport lifecycle, inbound dispatch, rid-correlated
    requests. Subclasses populate `self._handlers` and add their own
    per-message-type logic (see PeerDispatchNode, OutpostNode)."""

    def __init__(self, *, node_id: str, transport: Transport) -> None:
        self.node_id = node_id
        self.transport = transport
        self._handlers: Dict[tuple[str, str], Handler] = {}
        self._pending: Dict[str, "asyncio.Future[Envelope]"] = {}
        self._seen_mids: set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._inflight: "set[asyncio.Task]" = set()

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
        for task in list(self._inflight):
            task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)
        await self.transport.stop()

    async def _loop(self) -> None:
        # Decoding, response-correlation, and mid dedup all happen here,
        # synchronously (no `await` between receive and dedup), before any
        # handler runs as its own task. That split matters: a handler may
        # need to issue its *own* outbound request and await a reply (e.g.
        # OutpostNode relaying directly to a co-located Pocket while still
        # replying to whoever handed it the message) — if handler execution
        # blocked this loop the way it used to, that nested reply could
        # never arrive, since nothing would be left running to receive it.
        # Running each handler as a separate task keeps the loop free to
        # keep receiving while a handler waits on something of its own.
        while True:
            packet = await self.transport.receive_one(timeout=None)
            try:
                env = decode_cbor(packet.payload)
            except Exception:
                logger.warning("malformed_packet node=%s", self.node_id)
                continue

            if env.flags & int(Flags.RESPONSE):
                fut = self._pending.pop(env.rid, None)
                if fut and not fut.done():
                    fut.set_result(env)
                continue

            if env.mid in self._seen_mids:
                continue
            self._seen_mids.add(env.mid)
            if len(self._seen_mids) > 2048:
                self._seen_mids = set(list(self._seen_mids)[-1024:])

            task = asyncio.create_task(self._dispatch(env))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _dispatch(self, env: Envelope) -> None:
        handler = self._handlers.get((env.svc, env.op))
        if handler is None:
            return
        try:
            reply = await handler(env)
        except Exception:
            logger.exception(
                "handler_failed node=%s svc=%s op=%s", self.node_id, env.svc, env.op
            )
            return
        if reply is not None:
            await self._send(reply)

    async def _send(self, env: Envelope) -> None:
        packet = TransportPacket(
            destination=env.dst,
            payload=encode_cbor(env),
            source=env.src or self.node_id,
            message_id=env.mid,
            ttl=env.ttl,
        )
        await self.transport.send(packet)

    async def request(self, env: Envelope, *, timeout: float = 5.0) -> Optional[Envelope]:
        """Send a request and await its correlated (by rid) response."""
        fut: "asyncio.Future[Envelope]" = asyncio.get_event_loop().create_future()
        self._pending[env.rid] = fut
        await self._send(env)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending.pop(env.rid, None)

    async def _is_direct_neighbor(self, dest_node_id: str) -> bool:
        """App-layer relay only pushes one hop; multi-hop is store-and-forward."""
        route = await self.transport.get_route(dest_node_id)
        return bool(route and route.hops == 1)
