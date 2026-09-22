"""PeerDispatchNode — Pocket-side Dispatch runtime (M3, sim-first).

Implements the "Offline / no-Station path" documented in docs/protocol.md
and docs/architecture.md ("Pocket↔Pocket and store-and-forward"):

  - `MSG_SEND` to a directly reachable peer delivers **locally** on receipt
    (the recipient reads now).
  - The recipient still retains a copy to carry toward Station.
  - `MSG_SYNC` uploads carried copies to Station (merged by `mid`) and, in
    the same round trip, Station piggybacks its own pending queue for this
    user back to the courier via the existing `MSG_PUSH` path.

This intentionally does not reuse WaylinkGateway: a Pocket must both accept
unsolicited requests (MSG_SEND from a peer, MSG_PUSH from Station) *and*
issue its own requests and await a correlated reply (MSG_SYNC) on the same
transport. WaylinkGateway dispatches inbound packets purely by (svc, op),
which is fine for Station (it only ever replies, never awaits a reply
itself) but would misread an awaited reply as a new inbound request on a
node that also handles that op. This class checks Flags.RESPONSE + rid
first, so it never touches WaylinkGateway or Station's behavior.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from server.services.dispatch.constants import (
    DELIVERY_DELIVERED,
    DELIVERY_ROUTED,
    DELIVERY_SENT,
    OP_MSG_PUSH,
    OP_MSG_SEND,
    OP_MSG_SYNC,
    TRANSPORT_LORA,
)
from server.services.dispatch.store import DispatchStore
from server.transports.base import Transport, TransportPacket
from shared.protocol.envelope import (
    SVC_DISPATCH,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
    new_id,
)

logger = logging.getLogger("waypost.dispatch.peer")

Handler = Callable[[Envelope], Awaitable[Optional[Envelope]]]

STATION_DEST = "station"


class PeerDispatchNode:
    """Pocket-side Dispatch: peer-to-peer delivery + carry-forward to Station."""

    def __init__(
        self,
        *,
        node_id: str,
        username: str,
        transport: Transport,
        store: DispatchStore,
    ) -> None:
        self.node_id = node_id
        self.username = username
        self.transport = transport
        self.store = store
        self._handlers: Dict[tuple[str, str], Handler] = {
            (SVC_DISPATCH, OP_MSG_SEND): self._on_incoming,
            (SVC_DISPATCH, OP_MSG_PUSH): self._on_incoming,
        }
        self._pending: Dict[str, "asyncio.Future[Envelope]"] = {}
        self._seen_mids: set[str] = set()
        self._task: Optional[asyncio.Task] = None

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
        while True:
            packet = await self.transport.receive_one(timeout=None)
            await self._handle_packet(packet)

    async def _handle_packet(self, packet: TransportPacket) -> None:
        try:
            env = decode_cbor(packet.payload)
        except Exception:
            logger.warning("malformed_packet node=%s", self.node_id)
            return

        if env.flags & int(Flags.RESPONSE):
            fut = self._pending.pop(env.rid, None)
            if fut and not fut.done():
                fut.set_result(env)
            return

        if env.mid in self._seen_mids:
            return
        self._seen_mids.add(env.mid)
        if len(self._seen_mids) > 2048:
            self._seen_mids = set(list(self._seen_mids)[-1024:])

        handler = self._handlers.get((env.svc, env.op))
        if handler is None:
            return
        reply = await handler(env)
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

    def _payload(
        self,
        message: dict[str, Any],
        *,
        final_dest: Optional[str] = None,
        for_user: Optional[str] = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "message": {
                "id": message["id"],
                "conversation_id": message["conversation_id"],
                "sender": message["sender"],
                "body": message["body"],
                "transport": message.get("transport"),
            }
        }
        if final_dest:
            out["final_dest"] = final_dest
        if for_user:
            out["for_user"] = for_user
        return out

    async def _is_direct_neighbor(self, dest_node_id: str) -> bool:
        """App-layer courier only pushes one hop; multi-hop is store-and-forward."""
        route = await self.transport.get_route(dest_node_id)
        return bool(route and route.hops == 1)

    async def send_direct(
        self,
        *,
        peer_username: str,
        peer_node_id: str,
        body: str,
        message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        conv = self.store.ensure_direct(self.username, peer_username)
        msg, created = self.store.add_message(
            conversation_id=conv["id"],
            sender=self.username,
            body=body,
            message_id=message_id,
            transport=TRANSPORT_LORA,
            delivery_state=DELIVERY_SENT,
        )
        if not created:
            return msg
        if await self._is_direct_neighbor(peer_node_id):
            delivered = await self._push_to(
                peer_node_id, msg, for_user=peer_username
            )
            if delivered:
                msg = self.store.set_delivery_state(msg["id"], DELIVERY_ROUTED) or msg
                return msg
        self.store.queue_courier(msg["id"], peer_node_id)
        return msg

    async def _push_to(
        self,
        dest_node_id: str,
        message: dict[str, Any],
        *,
        final_dest: Optional[str] = None,
        for_user: Optional[str] = None,
    ) -> bool:
        env = Envelope(
            src=self.node_id,
            dst=dest_node_id,
            svc=SVC_DISPATCH,
            op=OP_MSG_SEND,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload=self._payload(
                message, final_dest=final_dest, for_user=for_user
            ),
        )
        reply = await self.request(env)
        return bool(reply and not (reply.flags & int(Flags.ERROR)))

    async def _on_incoming(self, env: Envelope) -> Envelope:
        payload = env.payload or {}
        m = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(m, dict) or not m.get("id") or not m.get("sender") or m.get("body") is None:
            return env.make_response(op=OP_MSG_PUSH, payload={"error": "invalid_message"}, error=True)

        final_dest = payload.get("final_dest") if isinstance(payload, dict) else None
        for_user = payload.get("for_user") if isinstance(payload, dict) else None

        # Multi-hop carry: this node is an intermediate courier, not the reader.
        if final_dest and str(final_dest) != self.node_id:
            peer_name = str(for_user or m.get("peer") or "unknown")
            conv = self.store.ensure_direct(str(m["sender"]), peer_name)
            msg, created = self.store.add_message(
                conversation_id=conv["id"],
                sender=str(m["sender"]),
                body=str(m["body"]),
                message_id=str(m["id"]),
                transport=m.get("transport"),
                delivery_state=DELIVERY_SENT,
            )
            self.store.queue_courier(msg["id"], str(final_dest))
            if created:
                logger.info(
                    "peer_courier_accepted node=%s mid=%s final=%s",
                    self.node_id,
                    msg["id"],
                    final_dest,
                )
            return env.make_response(
                op=OP_MSG_PUSH,
                payload={"ok": True, "id": msg["id"], "courier": True},
                flags=Flags.RESPONSE | Flags.ACK,
            )

        # Direct delivery: recipient reads now, still carries a copy to Station.
        conv = self.store.ensure_direct(self.username, str(m["sender"]))
        msg, created = self.store.add_message(
            conversation_id=conv["id"],
            sender=str(m["sender"]),
            body=str(m["body"]),
            message_id=str(m["id"]),
            transport=m.get("transport"),
            delivery_state=DELIVERY_DELIVERED,
        )
        if created:
            self.store.queue_courier(msg["id"], STATION_DEST)
            logger.info("peer_delivered_locally node=%s mid=%s", self.node_id, msg["id"])
        return env.make_response(
            op=OP_MSG_PUSH, payload={"ok": True, "id": msg["id"]}, flags=Flags.RESPONSE | Flags.ACK
        )

    async def flush_pending(self, peer_node_id: str) -> int:
        """Retry courier items addressed to peer_node_id now that it's a neighbor."""
        pending = self.store.list_courier_pending(peer_node_id)
        count = 0
        for row in pending:
            if not await self._is_direct_neighbor(peer_node_id):
                break
            if await self._push_to(peer_node_id, row):
                self.store.set_delivery_state(row["message_id"], DELIVERY_ROUTED)
                self.store.clear_courier(row["message_id"], peer_node_id)
                count += 1
        return count

    async def handoff_to(self, neighbor_node_id: str) -> int:
        """Pass courier items for *other* destinations to a one-hop neighbor.

        The neighbor stores them and later delivers (or hands off again) —
        Pocket-as-courier multi-hop without requiring a transport path to the
        final node.
        """
        if not await self._is_direct_neighbor(neighbor_node_id):
            return 0
        # First deliver anything actually addressed to this neighbor
        handed = await self.flush_pending(neighbor_node_id)
        for row in list(self.store.list_courier_all()):
            dest = str(row.get("dest") or "")
            if dest in (neighbor_node_id, STATION_DEST, ""):
                continue
            # Infer recipient username from DM conversation id when possible
            for_user = None
            cid = str(row.get("conversation_id") or "")
            if cid.startswith("dm:"):
                parts = cid.split(":")
                if len(parts) == 3:
                    a, b = parts[1], parts[2]
                    for_user = b if a == self.username.lower() else a
            ok = await self._push_to(
                neighbor_node_id,
                row,
                final_dest=dest,
                for_user=for_user,
            )
            if ok:
                self.store.clear_courier(row["message_id"], dest)
                handed += 1
                logger.info(
                    "peer_handoff node=%s via=%s mid=%s final=%s",
                    self.node_id,
                    neighbor_node_id,
                    row["message_id"],
                    dest,
                )
        return handed

    async def sync_with_station(
        self, station_node_id: str = STATION_DEST, *, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Upload carried copies to Station; Station piggybacks its own
        pending queue for this user back inline in the same response."""
        pending = self.store.list_courier_pending(station_node_id)
        batch = [
            {
                "id": row["id"],
                "conversation_id": row["conversation_id"],
                "sender": row["sender"],
                "body": row["body"],
                "transport": row.get("transport"),
                "delivery_state": row.get("delivery_state") or DELIVERY_DELIVERED,
            }
            for row in pending
        ]
        env = Envelope(
            src=self.node_id,
            dst=station_node_id,
            svc=SVC_DISPATCH,
            op=OP_MSG_SYNC,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={"username": self.username, "messages": batch},
        )
        reply = await self.request(env, timeout=timeout)
        ok = bool(reply and not (reply.flags & int(Flags.ERROR)))
        received = 0
        if ok:
            for row in pending:
                self.store.clear_courier(row["message_id"], station_node_id)
            incoming = (reply.payload or {}).get("pending") or []
            for m in incoming:
                if (
                    not isinstance(m, dict)
                    or not m.get("id")
                    or not m.get("sender")
                    or m.get("body") is None
                ):
                    continue
                conv = self.store.ensure_direct(self.username, str(m["sender"]))
                _, created = self.store.add_message(
                    conversation_id=conv["id"],
                    sender=str(m["sender"]),
                    body=str(m["body"]),
                    message_id=str(m["id"]),
                    transport=m.get("transport"),
                    delivery_state=DELIVERY_DELIVERED,
                )
                if created:
                    received += 1
        return {
            "ok": ok,
            "synced": len(pending) if ok else 0,
            "received": received,
        }
