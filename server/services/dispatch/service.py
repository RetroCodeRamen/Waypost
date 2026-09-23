"""Dispatch service — shared by HTTP and Waylink."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

from server.services.dispatch.constants import (
    DELIVERY_DELIVERED,
    DELIVERY_QUEUED,
    DELIVERY_SENT,
    OP_MSG_ACK,
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
    OP_MSG_SYNC,
    TRANSPORT_LORA,
    TRANSPORT_WIFI,
)
from server.services.dispatch.store import DispatchStore, direct_conversation_id
from shared.protocol.envelope import (
    SVC_DISPATCH,
    Envelope,
    Flags,
    new_id,
)

logger = logging.getLogger("waypost.dispatch")


class DispatchService:
    def __init__(self, store: DispatchStore) -> None:
        self.store = store
        self._outbox: Dict[str, Deque[dict[str, Any]]] = defaultdict(deque)
        # Optional: push envelopes over radio (serial/Reticulum) as well as HTTP outbox
        self._radio_push = None  # Callable[[Envelope], None]
        # Avoid duplicate outbox entries for the same (node, message) before ACK
        self._queued_push_keys: set[tuple[str, str]] = set()

    def set_radio_push(self, callback) -> None:
        """Register a sink that transmits push envelopes on the live radio path."""
        self._radio_push = callback

    def sync_status(self) -> dict[str, Any]:
        """N1: visible pending sync for Signal / Today."""
        by_user = self.store.count_pending_by_user()
        outbox_depth = sum(len(q) for q in self._outbox.values())
        return {
            "pending_dispatch": self.store.count_pending(),
            "pending_by_user": by_user,
            "outbox_depth": outbox_depth,
            "waiting_nodes": sorted(
                node for node, q in self._outbox.items() if q
            ),
        }

    def bind_device(
        self,
        node_id: str,
        username: str,
        *,
        transport_dest: Optional[str] = None,
    ) -> dict[str, Any]:
        binding = self.store.bind_device(
            node_id, username, transport_dest=transport_dest
        )
        flushed = self._flush_pending_for_user(username, node_id)
        binding["flushed"] = flushed
        return binding

    def unbind_user(self, username: str) -> dict[str, Any]:
        nodes = self.store.nodes_for_user(username)
        n = self.store.unbind_user(username)
        for node_id in nodes:
            self._outbox.pop(node_id, None)
            self._queued_push_keys = {
                k for k in self._queued_push_keys if k[0] != node_id
            }
        return {"username": username, "unbound": n}

    def list_devices(self, username: str) -> list[dict[str, Any]]:
        return self.store.list_bindings_for_user(username)

    def unbind_device(self, node_id: str, *, username: str) -> dict[str, Any]:
        """Revoke exactly one device — the sibling of unbind_user, which
        wipes every device a user has. Raises ValueError if node_id isn't
        bound to username (ownership check, same shape as the HTTP route
        guards elsewhere in this module)."""
        binding = self.store.get_binding(node_id)
        if not binding or binding["username"].lower() != username.lower():
            raise ValueError("device not found")
        ok = self.store.unbind_device(node_id)
        if ok:
            self._outbox.pop(node_id, None)
            self._queued_push_keys = {
                k for k in self._queued_push_keys if k[0] != node_id
            }
        return {"node_id": node_id, "unbound": ok}

    def _flush_pending_for_user(self, username: str, node_id: str) -> int:
        """Enqueue pending pushes for a newly reachable node.

        Does **not** clear SQLite pending until delivery is confirmed
        (HTTP outbox poll or MSG_ACK) so reboot / deaf radio cannot drop mail.
        """
        pending = self.store.list_pending_for_user(username)
        count = 0
        for row in pending:
            msg = {
                "id": row["message_id"],
                "conversation_id": row["conversation_id"],
                "sender": row["sender"],
                "body": row["body"],
                "created_at": row["created_at"],
                "transport": row.get("transport"),
                "delivery_state": row.get("delivery_state"),
            }
            if self._enqueue_push(node_id, msg):
                count += 1
        if count:
            logger.info("flushed_pending user=%s node=%s count=%s", username, node_id, count)
        return count

    def _mark_push_delivered(self, node_id: str, message_id: str) -> None:
        binding = self.store.get_binding(node_id)
        if binding:
            self._confirm_delivered(binding["username"], message_id)
        self._queued_push_keys.discard((node_id, message_id))

    def _confirm_delivered(self, username: str, message_id: str) -> None:
        """Delivery confirmed on any path: clear pending and drop the copies
        still queued for the user's other devices (Wi‑Fi↔LoRa failover)."""
        self.store.clear_pending(message_id, username)
        if not self.store.pending_usernames_for_message(message_id):
            self.store.set_delivery_state(message_id, DELIVERY_DELIVERED)
        for other in self.store.nodes_for_user(username):
            q = self._outbox.get(other)
            if q:
                kept = [
                    env
                    for env in q
                    if not (
                        env.get("op") == OP_MSG_PUSH
                        and ((env.get("payload") or {}).get("message") or {}).get("id")
                        == message_id
                    )
                ]
                if len(kept) != len(q):
                    self._outbox[other] = deque(kept)
            self._queued_push_keys.discard((other, message_id))

    def send_direct(
        self,
        *,
        sender: str,
        peer: str,
        body: str,
        message_id: Optional[str] = None,
        transport: str = TRANSPORT_WIFI,
    ) -> dict[str, Any]:
        conv = self.store.ensure_direct(sender, peer)
        return self.send_to_conversation(
            conversation_id=conv["id"],
            sender=sender,
            body=body,
            message_id=message_id,
            transport=transport,
        )

    def create_room(
        self,
        *,
        title: str,
        members: list[str],
        slug: Optional[str] = None,
    ) -> dict[str, Any]:
        if not members:
            raise ValueError("room requires members")
        return self.store.create_room(title=title, members=members, slug=slug)

    def send_to_conversation(
        self,
        *,
        conversation_id: str,
        sender: str,
        body: str,
        message_id: Optional[str] = None,
        transport: str = TRANSPORT_WIFI,
    ) -> dict[str, Any]:
        if not body.strip():
            raise ValueError("empty message body")
        conv = self.store.get_conversation(conversation_id)
        if not conv:
            raise ValueError("conversation not found")
        if not self.store.is_member(conversation_id, sender):
            raise ValueError("sender is not a conversation member")

        msg, created = self.store.add_message(
            conversation_id=conversation_id,
            sender=sender,
            body=body.strip(),
            message_id=message_id,
            transport=transport,
            delivery_state=DELIVERY_SENT,
        )
        if created:
            offline_any, pushed_any = self._fanout_push(msg, exclude_username=sender)
            if offline_any:
                state = DELIVERY_QUEUED
            elif pushed_any:
                state = DELIVERY_SENT
            else:
                state = DELIVERY_DELIVERED
            msg = self.store.set_delivery_state(msg["id"], state) or msg
        return {
            "conversation": conv,
            "message": msg,
            "created": created,
        }

    def _message_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        # Keep MSG_PUSH under LoRa MAX_FRAME (250B): no created_at / delivery_state
        return {
            "message": {
                "id": message["id"],
                "conversation_id": message["conversation_id"],
                "sender": message["sender"],
                "body": message["body"],
                "transport": message.get("transport"),
            }
        }

    def _enqueue_push(self, node_id: str, message: dict[str, Any]) -> bool:
        """Queue a MSG_PUSH for node. Returns False if already queued for this node."""
        key = (node_id, message["id"])
        if key in self._queued_push_keys:
            return False
        env = Envelope(
            src="station",
            dst=node_id,
            svc=SVC_DISPATCH,
            op=OP_MSG_PUSH,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload=self._message_payload(message),
        )
        self._outbox[node_id].append(env.to_dict())
        self._queued_push_keys.add(key)
        # Air-TX to radio-* (Heltec) and rns-* (Reticulum) peers; HTTP outbox for pocket-*
        if self._radio_push is not None and (
            str(node_id).startswith("radio-") or str(node_id).startswith("rns-")
        ):
            try:
                self._radio_push(env)
            except Exception:
                # SQLite pending row stays until a device confirms, so a later bind/retry recovers
                logger.exception("radio_push_failed node=%s mid=%s", node_id, message["id"])
        logger.info(
            "dispatch_push node=%s mid=%s conv=%s",
            node_id,
            message["id"],
            message["conversation_id"],
        )
        return True

    def _fanout_push(
        self, message: dict[str, Any], *, exclude_username: str
    ) -> tuple[bool, bool]:
        """Return (any recipient offline, any push handed to a bound device).

        Every recipient gets a durable pending row until a device confirms
        delivery — a bound Pocket may already be out of range.
        """
        queued_offline = False
        pushed = False
        members = self.store.member_usernames(message["conversation_id"])
        for username in members:
            if username.lower() == exclude_username.lower():
                continue
            self.store.queue_pending_push(message["id"], username)
            nodes = self.store.nodes_for_user(username)
            if nodes:
                for node_id in nodes:
                    self._enqueue_push(node_id, message)
                pushed = True
            else:
                queued_offline = True
                logger.info(
                    "dispatch_queued_offline user=%s mid=%s",
                    username,
                    message["id"],
                )
        return queued_offline, pushed

    def poll_outbox(self, node_id: str, *, max_items: int = 20) -> list[dict[str, Any]]:
        q = self._outbox[node_id]
        items: list[dict[str, Any]] = []
        while q and len(items) < max_items:
            env = q.popleft()
            items.append(env)
            # HTTP mock Pocket polling counts as delivery confirmation
            if env.get("op") == OP_MSG_PUSH:
                mid = ((env.get("payload") or {}).get("message") or {}).get("id")
                if mid:
                    self._mark_push_delivered(node_id, str(mid))
        return items

    def list_conversations(self, username: str) -> list[dict[str, Any]]:
        return self.store.list_conversations(username)

    def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
        after_ts: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        return self.store.list_messages(conversation_id, limit=limit, after_ts=after_ts)

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        return self.store.get_conversation(conversation_id)

    async def handle_rpc(self, env: Envelope) -> Optional[Envelope]:
        if env.op == OP_MSG_SEND:
            return await self._rpc_send(env)
        if env.op == OP_MSG_LIST:
            return await self._rpc_list(env)
        if env.op == OP_MSG_ACK:
            return await self._rpc_ack(env)
        if env.op == OP_MSG_SYNC:
            return await self._rpc_sync(env)
        if env.op == OP_MSG_PUSH and env.flags & int(Flags.RESPONSE):
            # A Pocket's reply to our MSG_PUSH doubles as its delivery ACK.
            payload = env.payload if isinstance(env.payload, dict) else {}
            if payload.get("id") and not env.flags & int(Flags.ERROR):
                self._mark_push_delivered(env.src, str(payload["id"]))
            return None
        return env.make_response(
            op=env.op,
            payload={"error": "unknown_operation", "op": env.op},
            error=True,
        )

    async def _rpc_send(self, env: Envelope) -> Envelope:
        payload = env.payload or {}
        if not isinstance(payload, dict):
            return env.make_response(
                op=OP_MSG_SEND, payload={"error": "invalid_payload"}, error=True
            )

        binding = self.store.get_binding(env.src)
        sender = payload.get("sender") or (binding["username"] if binding else None)
        body = payload.get("body") or payload.get("text")
        message_id = payload.get("message_id") or env.mid
        conversation_id = payload.get("conversation_id")
        peer = payload.get("peer") or payload.get("to")

        if not sender or body is None:
            return env.make_response(
                op=OP_MSG_SEND,
                payload={"error": "sender_and_body_required"},
                error=True,
            )

        try:
            if conversation_id:
                result = self.send_to_conversation(
                    conversation_id=str(conversation_id),
                    sender=str(sender),
                    body=str(body),
                    message_id=str(message_id),
                    transport=str(payload.get("transport") or TRANSPORT_LORA),
                )
            elif peer:
                result = self.send_direct(
                    sender=str(sender),
                    peer=str(peer),
                    body=str(body),
                    message_id=str(message_id),
                    transport=str(payload.get("transport") or TRANSPORT_LORA),
                )
            else:
                return env.make_response(
                    op=OP_MSG_SEND,
                    payload={"error": "peer_or_conversation_id_required"},
                    error=True,
                )
        except ValueError as exc:
            return env.make_response(
                op=OP_MSG_SEND, payload={"error": str(exc)}, error=True
            )

        return env.make_response(
            op=OP_MSG_SEND,
            payload={
                "ok": True,
                "created": result["created"],
                "id": result["message"]["id"],
                "conversation_id": result["conversation"]["id"],
                "delivery_state": result["message"]["delivery_state"],
                # Compact echo for Wi‑Fi/mock clients; avoid nesting full message (LoRa budget)
                "transport": result["message"].get("transport"),
            },
            flags=Flags.RESPONSE | Flags.ACK,
        )

    async def _rpc_list(self, env: Envelope) -> Envelope:
        payload = env.payload or {}
        if not isinstance(payload, dict):
            return env.make_response(
                op=OP_MSG_LIST, payload={"error": "invalid_payload"}, error=True
            )
        conversation_id = payload.get("conversation_id")
        if not conversation_id:
            peer = payload.get("peer")
            binding = self.store.get_binding(env.src)
            username = payload.get("username") or (binding["username"] if binding else None)
            if username and peer:
                conversation_id = direct_conversation_id(str(username), str(peer))
            else:
                return env.make_response(
                    op=OP_MSG_LIST,
                    payload={"error": "conversation_id_or_peer_required"},
                    error=True,
                )
        limit = min(int(payload.get("limit") or 20), 20)
        # LoRa replies must stay under ~250B — return at most 3 compact rows on radio path
        if str(env.src).startswith("radio-") or str(env.src).startswith("rns-"):
            limit = min(limit, 3)
        messages = self.list_messages(str(conversation_id), limit=limit)
        compact = [
            {
                "id": m["id"],
                "sender": m["sender"],
                "body": (m["body"] or "")[:80],
                "ts": m["created_at"],
                "state": m["delivery_state"],
                "conv": m["conversation_id"],
            }
            for m in messages
        ]
        return env.make_response(
            op=OP_MSG_LIST,
            payload={"conversation_id": conversation_id, "messages": compact},
        )

    async def _rpc_ack(self, env: Envelope) -> Envelope:
        payload = env.payload or {}
        if not isinstance(payload, dict) or not payload.get("message_id"):
            return env.make_response(
                op=OP_MSG_ACK, payload={"error": "message_id_required"}, error=True
            )
        state = str(payload.get("state") or DELIVERY_DELIVERED)
        message_id = str(payload["message_id"])
        msg = self.store.set_delivery_state(message_id, state)
        if not msg:
            return env.make_response(
                op=OP_MSG_ACK, payload={"error": "not_found"}, error=True
            )
        # Radio / peer ACK clears opportunistic pending for this node
        self._mark_push_delivered(env.src, message_id)
        return env.make_response(
            op=OP_MSG_ACK, payload={"ok": True, "id": message_id}, flags=Flags.RESPONSE | Flags.ACK
        )

    async def _rpc_sync(self, env: Envelope) -> Envelope:
        """M3: ingest a courier's carried copies (dedup by mid) and piggyback
        this user's own pending queue back inline, in the same round trip —
        the sync response itself is the delivery confirmation, so pending
        rows are cleared directly rather than via a separate push/ACK.

        See docs/protocol.md "Offline / no-Station path" and
        docs/architecture.md "Pocket↔Pocket and store-and-forward".
        """
        payload = env.payload or {}
        if not isinstance(payload, dict):
            return env.make_response(
                op=OP_MSG_SYNC, payload={"error": "invalid_payload"}, error=True
            )
        username = payload.get("username")
        messages = payload.get("messages")
        if not username or not isinstance(messages, list):
            return env.make_response(
                op=OP_MSG_SYNC,
                payload={"error": "username_and_messages_required"},
                error=True,
            )

        # Courier must be a bound device for this username (radio authz stand-in).
        binding = self.store.get_binding(env.src)
        if (
            not binding
            or str(binding["username"]).lower() != str(username).lower()
        ):
            return env.make_response(
                op=OP_MSG_SYNC,
                payload={"error": "unauthorized_courier"},
                error=True,
            )

        ingested = 0
        for m in messages:
            if (
                not isinstance(m, dict)
                or not m.get("id")
                or not m.get("sender")
                or m.get("body") is None
            ):
                continue
            conv = self.store.ensure_direct(str(m["sender"]), str(username))
            _, created = self.store.add_message(
                conversation_id=conv["id"],
                sender=str(m["sender"]),
                body=str(m["body"]),
                message_id=str(m["id"]),
                transport=m.get("transport"),
                delivery_state=str(m.get("delivery_state") or DELIVERY_DELIVERED),
            )
            if created:
                ingested += 1

        pending_rows = self.store.list_pending_for_user(str(username))
        piggyback: list[dict[str, Any]] = []
        for row in pending_rows:
            piggyback.append(
                {
                    "id": row["message_id"],
                    "conversation_id": row["conversation_id"],
                    "sender": row["sender"],
                    "body": row["body"],
                    "transport": row.get("transport"),
                }
            )
            self._confirm_delivered(str(username), row["message_id"])

        logger.info(
            "dispatch_sync courier=%s user=%s ingested=%s piggyback=%s",
            env.src,
            username,
            ingested,
            len(piggyback),
        )
        return env.make_response(
            op=OP_MSG_SYNC,
            payload={"ok": True, "ingested": ingested, "pending": piggyback},
            flags=Flags.RESPONSE | Flags.ACK,
        )
