"""SyncNode — a simulated Waypost device (Scout, Outpost, courier) that
holds signed objects and syncs them with whoever it meets (roadmap D4).

The Python stand-in for what the firmware does; drives the tests in
server/tests/test_peer_sync.py over MockMesh.
"""

from __future__ import annotations

from typing import Any, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.services.dispatch.store import direct_conversation_id
from server.services.dispatch.waylink_node import WaylinkPeerNode
from server.services.identity import objects as O
from server.services.sync.engine import (
    OP_HELLO,
    OP_PUT,
    OP_SUM,
    OP_WANT,
    SVC_SYNC,
    SyncResponder,
    SyncResult,
    sync_with,
)
from server.services.sync.sets import MemoryObjectSet
from server.transports.base import Transport
from shared.protocol.envelope import Envelope, Flags


class SyncNode(WaylinkPeerNode):
    def __init__(
        self,
        *,
        node_id: str,
        transport: Transport,
        objects: MemoryObjectSet,
        role: str,
        interests: list[str],
        username: str = "",
        signing_key: Optional[Ed25519PrivateKey] = None,  # the person's identity key
        identity_id: bytes = b"",
    ) -> None:
        super().__init__(node_id=node_id, transport=transport)
        self.objects = objects
        self.role = role
        self.interests = interests
        self.username = username
        self.signing_key = signing_key
        self.identity_id = identity_id
        self.responder = SyncResponder(objects, role=role, interests=lambda: self.interests)
        for op in (OP_HELLO, OP_SUM, OP_WANT, OP_PUT):
            self._handlers[(SVC_SYNC, op)] = self.responder.handle_rpc

    def write(self, body: str, *, peer: str = "", conv: str = "", t: int = 1_791_000_000) -> dict[str, Any]:
        """Author a signed message (what the Scout does at compose)."""
        obj = {"k": O.KIND_DISPATCH_MSG, "o": O.new_oid(), "u": self.username, "a": self.identity_id,
               "v": conv or direct_conversation_id(self.username, peer), "b": body, "t": t}
        obj["s"] = self.signing_key.sign(O.canonical_bytes(obj))
        created, code = self.objects.put(obj)
        assert created and not code, code
        return obj

    async def sync(self, peer_node_id: str, *, timeout: float = 2.0) -> SyncResult:
        async def request(op: str, payload: dict[str, Any]) -> Optional[Envelope]:
            env = Envelope(src=self.node_id, dst=peer_node_id, svc=SVC_SYNC, op=op,
                           flags=int(Flags.REQUEST), payload=payload)
            return await self.request(env, timeout=timeout)

        return await sync_with(request, self.objects, role=self.role, interests=self.interests)
