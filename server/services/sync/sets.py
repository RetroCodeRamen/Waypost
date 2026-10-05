"""Object sets the sync engine reconciles (server/services/sync/engine.py).

- ``MemoryObjectSet`` — a node's own store, verified offline from cached
  certificates (simulated Scouts and Outposts; the shape the firmware
  follows).
- ``StationObjectSet`` — Station's Dispatch history: every *signed* message
  (unsigned ones can't be checked by anyone else, so they don't travel).
"""

from __future__ import annotations

from typing import Any, Optional

from server.services.identity.objects import KIND_DISPATCH_MSG, OfflineVerifier
from server.services.sync.engine import in_scope


class MemoryObjectSet:
    def __init__(self, verifier: OfflineVerifier) -> None:
        self.verifier = verifier
        self.objects: dict[bytes, dict[str, Any]] = {}
        self.arrivals: list[dict[str, Any]] = []  # new objects, in arrival order

    def oids(self, scope: str) -> list[bytes]:
        return [o for o, obj in self.objects.items() if in_scope(scope, obj)]

    def get(self, oid: bytes) -> Optional[dict[str, Any]]:
        return self.objects.get(bytes(oid))

    def owner_of(self, identity_id: bytes) -> Optional[str]:
        return self.verifier.owner_of(identity_id)

    def put(self, obj: dict[str, Any]) -> tuple[bool, str]:
        if bytes(obj["o"]) in self.objects:
            return False, ""
        code = self.verifier.verify(obj)
        if code:
            return False, code
        self.objects[bytes(obj["o"])] = dict(obj)
        self.arrivals.append(dict(obj))
        return True, ""


class StationObjectSet:
    """Station's signed Dispatch messages. Arrivals go through the same
    path as a signed MSG_SEND (verify, store, push to whoever's online)."""

    def __init__(self, dispatch, identity) -> None:
        self.dispatch = dispatch
        self.store = dispatch.store
        self.identity = identity  # IdentityService

    def _rows(self, scope: str) -> list[dict[str, Any]]:
        conn = self.store._conn
        if scope == "*":
            rows = conn.execute("SELECT * FROM messages WHERE sig IS NOT NULL AND author_id IS NOT NULL").fetchall()
        elif scope.startswith("u:"):
            rows = conn.execute(
                """SELECT DISTINCT m.* FROM messages m
                   LEFT JOIN conversation_members cm ON cm.conversation_id = m.conversation_id
                   WHERE m.sig IS NOT NULL AND m.author_id IS NOT NULL
                     AND (cm.username = ? COLLATE NOCASE OR m.sender = ? COLLATE NOCASE)""",
                (scope[2:], scope[2:]),
            ).fetchall()
        elif scope.startswith("c:"):
            rows = conn.execute(
                "SELECT * FROM messages WHERE sig IS NOT NULL AND author_id IS NOT NULL AND conversation_id = ?",
                (scope[2:],),
            ).fetchall()
        else:
            rows = []
        return [dict(r) for r in rows]

    @staticmethod
    def _obj(row: dict[str, Any]) -> dict[str, Any]:
        return {"k": KIND_DISPATCH_MSG, "o": bytes.fromhex(row["id"]), "u": row["sender"],
                "a": bytes.fromhex(row["author_id"]), "v": row["conversation_id"], "b": row["body"],
                "t": int(row["signed_at"] or 0), "s": bytes.fromhex(row["sig"])}

    def oids(self, scope: str) -> list[bytes]:
        return [bytes.fromhex(r["id"]) for r in self._rows(scope) if in_scope(scope, self._obj(r))]

    def get(self, oid: bytes) -> Optional[dict[str, Any]]:
        row = self.store.get_message(bytes(oid).hex())
        return self._obj(row) if row and row.get("sig") and row.get("author_id") else None

    def owner_of(self, identity_id: bytes) -> Optional[str]:
        return self.identity.owner_of(identity_id)

    def put(self, obj: dict[str, Any]) -> tuple[bool, str]:
        return self.dispatch.ingest_signed(obj)
