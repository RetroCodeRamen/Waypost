"""OutpostNode — LoRa relay infrastructure (M6, sim-first).

An Outpost is infrastructure, not a person's device: it has no username
and is never the final recipient of a Dispatch message the way a Pocket
is. Its job is purely to move messages closer to where they're going —
toward Station, or directly to a Pocket recipient that happens to be in
range right now — and it is deliberately **not** subject to
`PeerDispatchNode.MAX_COURIER_HOPS`: that cap governs battery-constrained
travel-device-to-travel-device chains, not fixed always-on infrastructure
(see docs/offline-sync.md).

Caveat worth keeping in mind: in a real Reticulum deployment, Outposts
running standard Reticulum transport-node firmware handle *live* multi-hop
routing mostly for free — that's Reticulum's own mesh routing, not app
code, moving a packet through several always-on relay radios when a path
currently exists. What this class is actually responsible for is the
store-and-forward fallback: no live path exists *right now*, so something
has to hold the message and retry later. It extends the same DTN mechanism
`PeerDispatchNode` already uses, not a replacement for Reticulum's routing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from server.services.corkboard.constants import OP_BOARD_SYNC
from server.services.corkboard.store import CorkboardStore
from server.services.dispatch.constants import OP_MSG_PUSH, OP_MSG_SEND
from server.services.dispatch.peer import COURIER_TTL_SECONDS, STATION_DEST
from server.services.dispatch.store import DispatchStore
from server.services.dispatch.waylink_node import WaylinkPeerNode
from server.transports.base import Transport
from shared.protocol.envelope import SVC_CORKBOARD, SVC_DISPATCH, Envelope, Flags, new_id

logger = logging.getLogger("waypost.dispatch.outpost")


class OutpostNode(WaylinkPeerNode):
    """Fixed relay infrastructure: uncapped hops, preferred-route caching
    to Station, direct hand-off between co-located Pockets."""

    def __init__(
        self,
        *,
        node_id: str,
        transport: Transport,
        store: DispatchStore,
        corkboard_store: CorkboardStore,
        display_name: Optional[str] = None,
        station_node_id: str = STATION_DEST,
    ) -> None:
        super().__init__(node_id=node_id, transport=transport)
        self.store = store
        self.corkboard_store = corkboard_store
        self.display_name = display_name
        self.station_node_id = station_node_id
        self._preferred_station_hop: Optional[str] = None
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

    async def _route_to_station(self) -> Optional[str]:
        """Prefer the cached next hop toward Station; rediscover (and
        re-cache) if it's gone stale. 'Find shortest route, then use it as
        the preferred method home' — with self-healing on failure."""
        if self._preferred_station_hop and await self._is_direct_neighbor(
            self._preferred_station_hop
        ):
            return self._preferred_station_hop
        route = await self.transport.get_route(self.station_node_id)
        if route and route.next_hop:
            self._preferred_station_hop = route.next_hop
            return route.next_hop
        self._preferred_station_hop = None
        return None

    async def relay_toward_station(self) -> int:
        """Push everything queued for Station via the preferred next hop.
        Uncapped — Station-bound relay through Outposts has no hop limit."""
        self.store.purge_expired_courier(COURIER_TTL_SECONDS)
        next_hop = await self._route_to_station()
        if not next_hop:
            return 0
        count = 0
        for row in self.store.list_courier_pending(self.station_node_id):
            if next_hop == self.station_node_id:
                # Last hop: Station speaks its own MSG_SEND shape (sender/
                # body/peer), not the courier relay envelope — reuse the
                # existing DispatchService._rpc_send unmodified rather than
                # teaching Station a second dialect.
                if not row.get("for_user"):
                    logger.warning(
                        "outpost_drop_no_recipient node=%s mid=%s",
                        self.node_id,
                        row["message_id"],
                    )
                    self.store.clear_courier(row["message_id"], self.station_node_id)
                    continue
                ok = await self._deliver_to_station(row)
            else:
                ok = await self._push_to(
                    next_hop,
                    row,
                    final_dest=self.station_node_id,
                    for_user=row.get("for_user"),
                    hops=int(row.get("hops") or 0) + 1,
                )
            if ok:
                self.store.clear_courier(row["message_id"], self.station_node_id)
                count += 1
            else:
                # Cached hop stopped working — force rediscovery next time.
                self._preferred_station_hop = None
                break
        return count

    async def _deliver_to_station(self, row: dict[str, Any]) -> bool:
        """Final hop only: Station's existing MSG_SEND handler
        (DispatchService._rpc_send) expects sender/body/peer directly, not
        the {message, final_dest, for_user, hops} relay envelope other
        nodes understand. message_id is threaded through so Station's
        mid-dedup treats this as the same message the original sender
        created, not a new one."""
        env = Envelope(
            src=self.node_id,
            dst=self.station_node_id,
            svc=SVC_DISPATCH,
            op=OP_MSG_SEND,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={
                "sender": row["sender"],
                "body": row["body"],
                "peer": row.get("for_user"),
                "message_id": row["id"],
                "transport": row.get("transport"),
            },
        )
        reply = await self.request(env)
        return bool(reply and not (reply.flags & int(Flags.ERROR)))

    async def relay_to_neighbor(self, neighbor_node_id: str) -> int:
        """Hand off everything queued for *other* destinations to a
        one-hop neighbor (another Outpost, or a Pocket courier). Uncapped —
        infrastructure-to-infrastructure hops don't count against
        PeerDispatchNode.MAX_COURIER_HOPS, which governs travel devices."""
        if not await self._is_direct_neighbor(neighbor_node_id):
            return 0
        self.store.purge_expired_courier(COURIER_TTL_SECONDS)
        handed = 0
        for row in list(self.store.list_courier_all()):
            dest = str(row.get("dest") or "")
            if dest in (neighbor_node_id, self.station_node_id, ""):
                continue
            ok = await self._push_to(
                neighbor_node_id,
                row,
                final_dest=dest,
                for_user=row.get("for_user"),
                hops=int(row.get("hops") or 0) + 1,
            )
            if ok:
                self.store.clear_courier(row["message_id"], dest)
                handed += 1
                logger.info(
                    "outpost_relay node=%s via=%s mid=%s final=%s",
                    self.node_id,
                    neighbor_node_id,
                    row["message_id"],
                    dest,
                )
        return handed

    async def _on_incoming(self, env: Envelope) -> Envelope:
        payload = env.payload or {}
        m = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(m, dict) or not m.get("id") or not m.get("sender") or m.get("body") is None:
            return env.make_response(op=OP_MSG_PUSH, payload={"error": "invalid_message"}, error=True)

        final_dest = str(payload.get("final_dest") or "") if isinstance(payload, dict) else ""
        for_user = payload.get("for_user") if isinstance(payload, dict) else None
        hops_in = int(payload.get("hops") or 0) if isinstance(payload, dict) else 0

        if not final_dest:
            return env.make_response(
                op=OP_MSG_PUSH, payload={"error": "final_dest_required"}, error=True
            )

        if final_dest == self.station_node_id:
            self.store.queue_courier(
                str(m["id"]), final_dest, hops=hops_in, for_user=for_user
            )
            self._remember_message(m)
            return env.make_response(
                op=OP_MSG_PUSH,
                payload={"ok": True, "id": m["id"], "relayed": "station"},
                flags=Flags.RESPONSE | Flags.ACK,
            )

        # A Pocket destination: hand off immediately if it's co-located
        # ("matching user devices" right here), else queue for later relay.
        if await self._is_direct_neighbor(final_dest):
            self._remember_message(m)
            delivered = await self._push_to(
                final_dest,
                self._as_row(m),
                final_dest=final_dest,
                for_user=for_user,
                hops=hops_in + 1,
            )
            if delivered:
                return env.make_response(
                    op=OP_MSG_PUSH,
                    payload={"ok": True, "id": m["id"], "relayed": "direct"},
                    flags=Flags.RESPONSE | Flags.ACK,
                )

        self._remember_message(m)
        self.store.queue_courier(
            str(m["id"]), final_dest, hops=hops_in, for_user=for_user
        )
        return env.make_response(
            op=OP_MSG_PUSH,
            payload={"ok": True, "id": m["id"], "relayed": "queued"},
            flags=Flags.RESPONSE | Flags.ACK,
        )

    def _relay_bucket(self) -> str:
        """A conversation_id this Outpost's relayed messages are filed
        under — not a real conversation (no conversations/members row is
        created; add_message doesn't require one). Namespaced by node_id
        so it can't collide with a real `dm:`/`room:` id, unlike a sentinel
        username, which a real account could register."""
        return f"relay:{self.node_id}"

    def _remember_message(self, m: dict[str, Any]) -> None:
        """Store just enough of the message body for the courier_queue
        JOIN to find it later, without making this Outpost a party to any
        real conversation."""
        self.store.add_message(
            conversation_id=self._relay_bucket(),
            sender=str(m["sender"]),
            body=str(m["body"]),
            message_id=str(m["id"]),
            transport=m.get("transport"),
            delivery_state="SENT",
        )

    @staticmethod
    def _as_row(m: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": m["id"],
            "conversation_id": m.get("conversation_id") or "",
            "sender": m["sender"],
            "body": m["body"],
            "transport": m.get("transport"),
        }

    # -- Corkboard: this Outpost's own public note board --

    def add_local_note(
        self, *, body: str, signature: Optional[str] = None
    ) -> dict[str, Any]:
        """A note authored at this Outpost (its own Wi-Fi local board, once
        that firmware exists — this is the method it would call). Stored
        under this node's own id, same shape Station will see it in once
        synced."""
        note, _ = self.corkboard_store.add_note(
            outpost_id=self.node_id, body=body, signature=signature
        )
        return note

    async def sync_corkboard(
        self, station_node_id: Optional[str] = None, *, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Upload this Outpost's not-yet-synced notes to Station and
        ingest whatever Station piggybacks back — same round trip shape as
        PeerDispatchNode.sync_with_station, but the local copy is never
        cleared (Corkboard's durability model is inverted from Dispatch's
        courier queue: the Outpost's copy stays, `synced_at` just marks
        that Station has it too)."""
        dst = station_node_id or self.station_node_id
        unsynced = self.corkboard_store.list_unsynced(self.node_id)
        batch = [
            {
                "id": n["id"],
                "body": n["body"],
                "signature": n.get("signature"),
                "created_at": n.get("created_at"),
            }
            for n in unsynced
        ]
        env = Envelope(
            src=self.node_id,
            dst=dst,
            svc=SVC_CORKBOARD,
            op=OP_BOARD_SYNC,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={"display_name": self.display_name, "notes": batch},
        )
        reply = await self.request(env, timeout=timeout)
        ok = bool(reply and not (reply.flags & int(Flags.ERROR)))
        received = 0
        if ok:
            for n in unsynced:
                self.corkboard_store.mark_synced(n["id"])
            pending = (reply.payload or {}).get("pending") or []
            for p in pending:
                if not isinstance(p, dict) or not p.get("id") or p.get("body") is None:
                    continue
                _, created = self.corkboard_store.add_note(
                    outpost_id=self.node_id,
                    body=str(p["body"]),
                    signature=p.get("signature"),
                    note_id=str(p["id"]),
                    created_at=p.get("created_at"),
                )
                # Station-composed notes arrive already-synced by definition.
                self.corkboard_store.mark_synced(str(p["id"]))
                if created:
                    received += 1
        return {"ok": ok, "synced": len(unsynced) if ok else 0, "received": received}
