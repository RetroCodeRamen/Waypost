"""PeerDispatchNode — Pocket-side Dispatch runtime (M3, sim-first).

Implements the "Offline / no-Station path" documented in docs/protocol.md
and docs/architecture.md ("Pocket↔Pocket and store-and-forward"):

  - `MSG_SEND` to a directly reachable peer delivers **locally** on receipt
    (the recipient reads now).
  - The recipient still retains a copy to carry toward Station.
  - `MSG_SYNC` uploads carried copies to Station (merged by `mid`) and, in
    the same round trip, Station piggybacks its own pending queue for this
    user back to the courier via the existing `MSG_PUSH` path.

See `server/services/dispatch/waylink_node.py` for why this is built on
`WaylinkPeerNode` rather than `WaylinkGateway`: a Pocket must both accept
unsolicited requests (MSG_SEND from a peer, MSG_PUSH from Station) *and*
issue its own requests and await a correlated reply (MSG_SYNC) on the same
transport, which `WaylinkGateway`'s reply-only dispatch can't do safely.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

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
from server.services.dispatch.waylink_node import WaylinkPeerNode
from server.transports.base import Transport
from shared.protocol.envelope import SVC_DISPATCH, Envelope, Flags, new_id

logger = logging.getLogger("waypost.dispatch.peer")

STATION_DEST = "station"

# Cap on device-to-device relay hops for a courier chain between travel
# devices (Pockets). Station-bound courier items are exempt — handoff_to's
# relay loop already never hands those to a neighbor (it waits for this
# node itself to reach Station directly), so nothing here needs to special
# case Station. Outposts (fixed, always-on infrastructure, unlike a
# battery-constrained Pocket) are meant to relay past this cap once they
# exist (M6) — this constant only governs travel-device-to-travel-device
# hops in the current sim.
MAX_COURIER_HOPS = 3

# How long an unsent courier copy may sit on a node's disk before it's
# dropped. A courier holds plaintext of messages it isn't a party to (see
# docs/security.md); this bounds that exposure and the storage growth,
# matching offline-sync.md's "courier queues are bounded; TTL/expiry
# applies" assumption, which had no enforcement until now.
COURIER_TTL_SECONDS = 24 * 60 * 60


class PeerDispatchNode(WaylinkPeerNode):
    """Pocket-side Dispatch: peer-to-peer delivery + carry-forward to Station."""

    def __init__(
        self,
        *,
        node_id: str,
        username: str,
        transport: Transport,
        store: DispatchStore,
    ) -> None:
        super().__init__(node_id=node_id, transport=transport)
        self.username = username
        self.store = store
        self._handlers = {
            (SVC_DISPATCH, OP_MSG_SEND): self._on_incoming,
            (SVC_DISPATCH, OP_MSG_PUSH): self._on_incoming,
        }

    def _payload(
        self,
        message: dict[str, Any],
        *,
        final_dest: Optional[str] = None,
        for_user: Optional[str] = None,
        hops: Optional[int] = None,
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
        if hops is not None:
            out["hops"] = hops
        return out

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
        self.store.queue_courier(msg["id"], peer_node_id, for_user=peer_username)
        return msg

    async def _push_to(
        self,
        dest_node_id: str,
        message: dict[str, Any],
        *,
        final_dest: Optional[str] = None,
        for_user: Optional[str] = None,
        hops: Optional[int] = None,
    ) -> bool:
        env = Envelope(
            src=self.node_id,
            dst=dest_node_id,
            svc=SVC_DISPATCH,
            op=OP_MSG_SEND,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload=self._payload(
                message, final_dest=final_dest, for_user=for_user, hops=hops
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
        hops_in = int(payload.get("hops") or 0) if isinstance(payload, dict) else 0

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
            self.store.queue_courier(
                msg["id"], str(final_dest), hops=hops_in, for_user=peer_name
            )
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
        self.store.purge_expired_courier(COURIER_TTL_SECONDS)
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
        self.store.purge_expired_courier(COURIER_TTL_SECONDS)
        # First deliver anything actually addressed to this neighbor
        handed = await self.flush_pending(neighbor_node_id)
        for row in list(self.store.list_courier_all()):
            dest = str(row.get("dest") or "")
            if dest in (neighbor_node_id, STATION_DEST, ""):
                continue
            hops = int(row.get("hops") or 0)
            if hops >= MAX_COURIER_HOPS:
                # At the travel-device hop cap — hold it (still deliverable
                # directly, or once Station/an Outpost is reached) but don't
                # relay it to yet another Pocket.
                logger.info(
                    "peer_handoff_capped node=%s mid=%s final=%s hops=%s",
                    self.node_id,
                    row["message_id"],
                    dest,
                    hops,
                )
                continue
            # Use the recipient username stored on the row (set when this
            # node first queued or accepted the item) — do NOT re-derive it
            # from the conversation id here: a pure courier is a party to
            # neither side of "dm:a:b", so any "am I a or b" heuristic
            # breaks past the first hop.
            for_user = row.get("for_user")
            ok = await self._push_to(
                neighbor_node_id,
                row,
                final_dest=dest,
                for_user=for_user,
                hops=hops + 1,
            )
            if ok:
                self.store.clear_courier(row["message_id"], dest)
                handed += 1
                logger.info(
                    "peer_handoff node=%s via=%s mid=%s final=%s hops=%s",
                    self.node_id,
                    neighbor_node_id,
                    row["message_id"],
                    dest,
                    hops + 1,
                )
        return handed

    async def sync_with_station(
        self, station_node_id: str = STATION_DEST, *, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Upload carried copies to Station; Station piggybacks its own
        pending queue for this user back inline in the same response."""
        self.store.purge_expired_courier(COURIER_TTL_SECONDS)
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
