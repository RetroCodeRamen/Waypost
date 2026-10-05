"""Dispatch service — shared by HTTP and Waylink."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, Optional

from server.services.dispatch.constants import (
    DELIVERY_DELIVERED,
    DELIVERY_QUEUED,
    DELIVERY_SENT,
    OP_MSG_ACK,
    OP_MSG_CONVS,
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
    OP_MSG_SYNC,
    TRANSPORT_LORA,
    TRANSPORT_WIFI,
)
from server.services.dispatch.store import DispatchStore, direct_conversation_id
from shared.protocol.radio import RADIO_MDU, chunk_utf8, fit_list_reply, fit_text_reply
from shared.protocol.envelope import (
    SVC_DISPATCH,
    Envelope,
    Flags,
    new_id,
)

logger = logging.getLogger("waypost.dispatch")


class DispatchService:
    def __init__(
        self,
        store: DispatchStore,
        *,
        is_trusted_courier: Optional[Callable[[str], bool]] = None,
        user_exists: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.store = store
        self._user_exists = user_exists
        # Claimed Outposts relay other people's messages (MSG_SEND with a
        # payload sender they aren't bound to); see _rpc_send.
        self._is_trusted_courier = is_trusted_courier or (lambda _node_id: False)
        self._outbox: Dict[str, Deque[dict[str, Any]]] = defaultdict(deque)
        # Optional: push envelopes over radio (serial/Reticulum) as well as HTTP outbox
        self._radio_push = None  # Callable[[Envelope], None]
        self._verify_object = None  # see set_object_verifier
        # Avoid duplicate outbox entries for the same (node, message) before ACK
        self._queued_push_keys: set[tuple[str, str]] = set()

    def set_object_verifier(self, verify) -> None:
        """Signed messages (roadmap D3): ``verify(obj, sig)`` returns
        (author username, "") or (None, error) — IdentityService.verify_object."""
        self._verify_object = verify

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
        signature: Optional[dict[str, Any]] = None,
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
            # A signed body is kept exactly as signed, so the signature can be
            # checked again later (and by others, once copies sync).
            body=body if signature else body.strip(),
            message_id=message_id,
            transport=transport,
            delivery_state=DELIVERY_SENT,
            signature=signature,
        )
        # A device may pick its own message id so a resend after a lost
        # reply is recognised (the Scout's outbox does this). A repeat must be
        # the same message, not someone else's id.
        if not created and (
            str(msg["sender"]).lower() != sender.lower()
            or msg["conversation_id"] != conversation_id
        ):
            raise ValueError("message_id_conflict")
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

    @staticmethod
    def _fit_push(env: Envelope, message: dict[str, Any]) -> Envelope:
        """A radio device only receives what fits one encrypted packet
        (shared/protocol/radio.py); a long message from the portal would
        otherwise never arrive at all. Cut the body to fit and mark it with
        an ellipsis — the whole message stays in history and on the portal."""
        from shared.protocol.envelope import encode_cbor

        if len(encode_cbor(env)) <= RADIO_MDU:
            return env
        body = str(message.get("body") or "")

        def build(piece: str) -> Envelope:
            payload = {"message": dict(env.payload["message"], body=piece + "…")}
            return Envelope(
                src=env.src, dst=env.dst, svc=env.svc, op=env.op, flags=env.flags,
                mid=env.mid, ttl=env.ttl, payload=payload,
            )

        return fit_text_reply(build, body, 0, len(body.encode("utf-8")))

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
        self._outbox[node_id].append(env.to_dict())  # Wi-Fi outbox: full body
        self._queued_push_keys.add(key)
        radio_env = self._fit_push(env, message)
        # Air-TX to radio-* (Heltec), rns-* (Reticulum), and pocket-* (Scout/
        # T-Deck -- LoRa-only, no Wi-Fi path to poll the HTTP outbox with).
        if self._radio_push is not None and self._is_radio_node(node_id):
            try:
                self._radio_push(radio_env)
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
        if env.op == OP_MSG_CONVS:
            return self._rpc_convs(env)
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

        # Who may say who sent this (same principle as Noticeboard/Beacon,
        # docs/protocol.md):
        # - a bound device (a Scout) sends only as its own user; a payload
        #   `sender` is accepted only when it agrees;
        # - a claimed Outpost may relay someone else's message, carrying the
        #   author in the payload (claimed Outposts are trusted relay
        #   infrastructure, as for BEACON_SYNC; signatures would make this
        #   end-to-end, see docs/security.md);
        # - anything else is rejected.
        if payload.get("s") is not None:
            return self._rpc_send_signed(env, payload)

        binding = self.store.get_binding(env.src)
        claimed = payload.get("sender")
        if binding:
            sender = binding["username"]
            if claimed and str(claimed).lower() != str(sender).lower():
                return env.make_response(
                    op=OP_MSG_SEND, payload={"error": "sender_mismatch"}, error=True
                )
        elif claimed and self._is_trusted_courier(str(env.src)):
            sender = claimed
        else:
            return env.make_response(
                op=OP_MSG_SEND, payload={"error": "unauthorized_device"}, error=True
            )
        body = payload.get("body") or payload.get("text")
        message_id = payload.get("message_id") or env.mid
        conversation_id = payload.get("conversation_id")
        peer = payload.get("peer") or payload.get("to")
        # From a radio device, a peer Station has never heard of is a typo or
        # a stale contact — say so instead of silently creating a dead-end
        # conversation (the portal's HTTP path keeps its create-on-send).
        if (
            peer
            and not conversation_id
            and self._user_exists is not None
            and not self._user_exists(str(peer))
        ):
            return env.make_response(
                op=OP_MSG_SEND, payload={"error": "unknown_user"}, error=True
            )

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

    def _rpc_send_signed(self, env: Envelope, payload: dict[str, Any]) -> Envelope:
        """A message signed by its author's device (roadmap D3): who sent it
        is whoever's certificate the signature checks against — not which
        device delivered it, so any node may carry it here.

        payload: o (16-byte object id), b (body), p (peer, direct) or v
        (conversation id), a (author's identity id), s (signature);
        the signed time is the envelope's ts (1 = the device didn't know the
        time; 0 can't be sent, the envelope reader replaces it with now)."""
        from server.services.dispatch.store import direct_conversation_id
        from server.services.identity import objects as O

        def err(code: str) -> Envelope:
            return env.make_response(op=OP_MSG_SEND, payload={"error": code}, error=True)

        if self._verify_object is None:
            return err("signatures_not_supported")
        oid, body, sig = payload.get("o"), payload.get("b"), payload.get("s")
        peer, conv = payload.get("p"), payload.get("v")
        if not isinstance(oid, bytes) or len(oid) != 16 or not isinstance(body, str) or not (peer or conv):
            return err("invalid_payload")
        if not body.strip():
            return err("sender_and_body_required")
        obj = {"k": O.KIND_DISPATCH_MSG, "o": oid, "a": payload.get("a"), "b": body,
               "t": int(env.ts or 0)}
        if conv:
            obj["v"] = str(conv)
        else:
            owner = self._author(obj.get("a"))
            if not owner:
                return err("unknown_identity")
            obj["v"] = direct_conversation_id(owner, str(peer))
        obj["u"], obj["s"] = self._author(obj.get("a")) or "", sig
        transport = str(payload.get("transport") or TRANSPORT_LORA)
        result, code = self._ingest(obj, transport)
        if code:
            return err(code)
        return env.make_response(
            op=OP_MSG_SEND,
            payload={
                "ok": True,
                "created": result["created"],
                "id": result["message"]["id"],
                "conversation_id": result["conversation"]["id"],
                "delivery_state": result["message"]["delivery_state"],
                "signed": True,
            },
            flags=Flags.RESPONSE | Flags.ACK,
        )

    def ingest_signed(self, obj: dict[str, Any]) -> tuple[bool, str]:
        """A signed message arriving by peer sync (SYNC PUT / WANT): verify,
        store, push to whoever is online. (created, "") or (False, error)."""
        result, code = self._ingest(obj, TRANSPORT_LORA)
        return (bool(result and result["created"]), code)

    def _ingest(self, obj: dict[str, Any], transport: str) -> tuple[Optional[dict[str, Any]], str]:
        if self._verify_object is None:
            return None, "signatures_not_supported"
        body = obj.get("b")
        if not isinstance(body, str) or not body.strip():
            return None, "sender_and_body_required"
        unsigned = {k: v for k, v in obj.items() if k not in ("s", "u")}
        author, code = self._verify_object(unsigned, obj.get("s"))
        if not author:
            return None, code
        conversation_id = str(obj["v"])
        if conversation_id.startswith("dm:"):
            a, b = conversation_id[3:].split(":", 1)
            if author.lower() not in (a, b):
                return None, "bad_signature"
            peer = b if a == author.lower() else a
            if self._user_exists is not None and not self._user_exists(peer):
                return None, "unknown_user"
            self.store.ensure_direct(author, peer)
        signature = {"sig": bytes(obj["s"]).hex(), "author_id": bytes(obj["a"]).hex(),
                     "signed_at": int(obj["t"])}
        try:
            result = self.send_to_conversation(
                conversation_id=conversation_id,
                sender=author,
                body=body,
                message_id=bytes(obj["o"]).hex(),
                transport=transport,
                signature=signature,
            )
        except ValueError as exc:
            return None, str(exc)
        return result, ""

    def set_author_lookup(self, lookup) -> None:
        """``lookup(identity id bytes) -> username | None`` (IdentityService.owner_of)."""
        self._author_lookup = lookup

    def _author(self, identity_id: Any) -> Optional[str]:
        lookup = getattr(self, "_author_lookup", None)
        if not lookup or not isinstance(identity_id, (bytes, bytearray)):
            return None
        return lookup(bytes(identity_id))

    async def _rpc_list(self, env: Envelope) -> Envelope:
        """Conversation history, radio-sized: newest first, as many whole
        messages as fit one packet; `skip` (how many newest messages the
        device already has) pages further back. `ts` is integer
        milliseconds (the Scout's CBOR reader has no floats).

        Only a bound device whose user is in the conversation may read it —
        direct conversation ids are predictable (dm:aj:bob)."""
        payload = env.payload or {}
        if not isinstance(payload, dict):
            return env.make_response(
                op=OP_MSG_LIST, payload={"error": "invalid_payload"}, error=True
            )
        binding = self.store.get_binding(env.src)
        if not binding:
            return env.make_response(
                op=OP_MSG_LIST, payload={"error": "unauthorized_device"}, error=True
            )
        username = binding["username"]
        conversation_id = payload.get("conversation_id")
        if not conversation_id and payload.get("peer"):
            conversation_id = direct_conversation_id(str(username), str(payload["peer"]))
        if not conversation_id:
            return env.make_response(
                op=OP_MSG_LIST,
                payload={"error": "conversation_id_or_peer_required"},
                error=True,
            )
        conversation_id = str(conversation_id)
        if not self.store.is_member(conversation_id, username):
            return env.make_response(
                op=OP_MSG_LIST, payload={"error": "not_a_member"}, error=True
            )
        rows = self.store.list_messages_newest(
            conversation_id, skip=int(payload.get("skip") or 0), limit=21
        )
        items = [
            {"id": m["id"], "s": m["sender"], "b": self._radio_body(m["body"]),
             "ts": int(m["created_at"] * 1000)}
            for m in rows
        ]

        def build(part: list[dict[str, Any]], more: bool) -> Envelope:
            # `more` also covers older rows we didn't fetch this time.
            return env.make_response(
                op=OP_MSG_LIST,
                payload={"conversation_id": conversation_id, "messages": part,
                         "more": more or len(rows) == 21},
            )

        reply, _ = fit_list_reply(build, items[:20])
        return reply

    @staticmethod
    def _is_radio_node(node_id: Any) -> bool:
        """Devices that only reach Station over LoRa: one packet per reply."""
        return str(node_id).startswith(("pocket-", "radio-", "rns-"))

    @staticmethod
    def _radio_body(body: Any, limit: int = 140) -> str:
        """Message bodies in radio listings: up to 140 bytes (the Scout's
        own limit), longer ones cut on a character boundary with an ellipsis."""
        text = str(body or "")
        piece, total = chunk_utf8(text, 0, limit)
        return piece if len(piece.encode("utf-8")) >= total else piece + "…"

    def _rpc_convs(self, env: Envelope) -> Envelope:
        """The bound user's conversations, newest activity first, paged by
        `offset`: {id, t (who it's with, or the room title), ts, from}."""
        payload = env.payload if isinstance(env.payload, dict) else {}
        binding = self.store.get_binding(env.src)
        if not binding:
            return env.make_response(
                op=OP_MSG_CONVS, payload={"error": "unauthorized_device"}, error=True
            )
        username = binding["username"]
        offset = max(0, int(payload.get("offset") or 0))
        items = []
        for c in self.store.list_conversations(username)[offset:]:
            if c.get("kind") == "direct":
                others = [m for m in c.get("members", []) if m.lower() != username.lower()]
                title = ", ".join(others) or username
            else:
                title = c.get("title") or c["id"]
            last = c.get("last_message") or {}
            items.append(
                {
                    "id": c["id"],
                    "t": str(title)[:32],
                    "ts": int(last.get("created_at") or c.get("updated_at") or 0),
                    "from": str(last.get("sender") or "")[:32],
                }
            )
        reply, _ = fit_list_reply(
            lambda part, more: env.make_response(
                op=OP_MSG_CONVS, payload={"conversations": part, "offset": offset, "more": more}
            ),
            items,
        )
        return reply

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

        # Piggyback this user's pending messages — only as many as fit one
        # radio packet, and only those are confirmed delivered; `more` tells
        # the device to sync again. (Previously everything went into one
        # reply and was marked delivered up front: a reply too big for the
        # radio never arrived and the messages were lost.)
        # Radio devices get one packet's worth (bodies cut to 140 bytes);
        # Wi-Fi/sim callers keep the whole queue with full bodies.
        radio = self._is_radio_node(env.src)
        pending_rows = self.store.list_pending_for_user(str(username))
        candidates = [
            {
                "id": row["message_id"],
                "conversation_id": row["conversation_id"],
                "sender": row["sender"],
                "body": self._radio_body(row["body"]) if radio else row["body"],
                "transport": row.get("transport"),
            }
            for row in pending_rows
        ]

        def build(part: list[dict[str, Any]], more: bool) -> Envelope:
            return env.make_response(
                op=OP_MSG_SYNC,
                payload={"ok": True, "ingested": ingested, "pending": part, "more": more},
                flags=Flags.RESPONSE | Flags.ACK,
            )

        if radio:
            reply, packed = fit_list_reply(build, candidates)
        else:
            reply, packed = build(candidates, False), len(candidates)
        piggyback = candidates[:packed]
        for item in piggyback:
            self._confirm_delivered(str(username), item["id"])

        logger.info(
            "dispatch_sync courier=%s user=%s ingested=%s piggyback=%s",
            env.src,
            username,
            ingested,
            len(piggyback),
        )
        return reply
