"""Peer sync (roadmap D4, docs/network-model.md §5): "objects this node knows
that the other may not" — one protocol for every pair of nodes (Scout,
Outpost, Station, a courier), any transport, no realtime path assumed.

Each node holds signed objects (today: ``dispatch.msg``, see
server/services/identity/objects.py) and declares **interests**:

    "*"        everything (Station, Outposts)
    "u:<name>" objects concerning a person (author or party to a direct
               conversation) — a Scout's own mailbox
    "c:<id>"   objects in one conversation (rooms)

Reconciling a scope is a walk down a 16-way tree of object-id prefixes. A
``SUM`` for a prefix returns either the object ids under it (when there
are few) or, for each next hex digit, a count and an 8-byte XOR
fingerprint — equal buckets are skipped. Mostly-in-sync nodes exchange a
few hundred bytes. Then ``WANT`` fetches one missing object per packet and
``PUT`` hands one over. Every object is verified on arrival, whoever
carried it.

Waylink ops (service ``SYNC``), every reply one packet:

    HELLO {r: role, i: [interests], h: [held]} -> {r, i, h}
          h: the scopes of objects a node carries for others (only nodes
          without "*" send it — it's how a courier's cargo gets found)
    SUM   {q: scope, p: hex prefix}            -> {n, x, oids: [...]} | {n, x, sub: [[n, x] x16]}
    WANT  {o: oid}                             -> object fields | {missing: true}
    PUT   object fields                        -> {ok, new} | error

Objects travel as their fields directly in the payload (no wrapper map —
every byte counts: a signed message at the Scout's compose limit must fit
these packets as well as MSG_SEND; see max_signed_body).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from shared.protocol.envelope import Envelope

logger = logging.getLogger("waypost.sync")

SVC_SYNC = "SYNC"
OP_HELLO = "HELLO"
OP_SUM = "SUM"
OP_WANT = "WANT"
OP_PUT = "PUT"

LIST_UNDER = 10  # a bucket this small is listed (10 x 16-byte ids fit one packet)
FP_LEN = 8       # fingerprint bytes per bucket (16 buckets fit one packet)
MAX_DEPTH = 8    # hex digits; 16^8 buckets is far beyond any Waypost


# -- objects ---------------------------------------------------------------------


def parties(obj: dict[str, Any]) -> set[str]:
    """People an object concerns: its author, and both people of a direct
    conversation. Room members aren't knowable from the object (scope c:)."""
    out = {str(obj.get("u", "")).lower()}
    conv = str(obj.get("v", ""))
    if conv.startswith("dm:"):
        out.update(p.lower() for p in conv[3:].split(":", 1))
    out.discard("")
    return out


def in_scope(scope: str, obj: dict[str, Any]) -> bool:
    if scope == "*":
        return True
    if scope.startswith("u:"):
        return scope[2:].lower() in parties(obj)
    if scope.startswith("c:"):
        return str(obj.get("v", "")) == scope[2:]
    return False


def wants(interests: Iterable[str], obj: dict[str, Any]) -> bool:
    return any(in_scope(q, obj) for q in interests)


def to_wire(obj: dict[str, Any]) -> dict[str, Any]:
    """Compact form for one packet: the author comes back from the
    certificate (``c``), a direct conversation is sent as the other person."""
    wire = {"o": obj["o"], "c": obj["c"], "b": obj["b"], "t": obj["t"], "s": obj["s"]}
    conv = str(obj["v"])
    if conv.startswith("dm:"):
        a, b = conv[3:].split(":", 1)
        wire["p"] = b if a == str(obj["u"]).lower() else a
    else:
        wire["v"] = conv
    return wire


def from_wire(wire: dict[str, Any], owner_of: Callable[[int], Optional[str]]) -> Optional[dict[str, Any]]:
    """Rebuilds the full object, or None when the certificate is unknown here."""
    from server.services.dispatch.store import direct_conversation_id
    from server.services.identity.objects import KIND_DISPATCH_MSG

    try:
        serial = int(wire["c"])
        author = owner_of(serial)
        if not author:
            return None
        conv = wire.get("v") or direct_conversation_id(author, str(wire["p"]))
        return {"k": KIND_DISPATCH_MSG, "o": bytes(wire["o"]), "u": author, "c": serial,
                "v": str(conv), "b": str(wire["b"]), "t": int(wire["t"]), "s": bytes(wire["s"])}
    except (KeyError, TypeError, ValueError):
        return None


# -- summaries -------------------------------------------------------------------


def fingerprint(oids: Iterable[bytes]) -> bytes:
    acc = bytearray(FP_LEN)
    for oid in oids:
        for i in range(FP_LEN):
            acc[i] ^= oid[i]
    return bytes(acc)


def under(oids: Iterable[bytes], prefix: str) -> list[bytes]:
    return [o for o in oids if o.hex().startswith(prefix)]


def summarize(oids: list[bytes], prefix: str) -> dict[str, Any]:
    mine = under(oids, prefix)
    out: dict[str, Any] = {"n": len(mine), "x": fingerprint(mine)}
    if len(mine) <= LIST_UNDER or len(prefix) >= MAX_DEPTH:
        out["oids"] = sorted(mine)
    else:
        out["sub"] = [
            [len(b), fingerprint(b)]
            for b in (under(mine, prefix + d) for d in "0123456789abcdef")
        ]
    return out


# -- a node's objects ----------------------------------------------------------------


class ObjectSet(Protocol):
    def oids(self, scope: str) -> list[bytes]: ...
    def get(self, oid: bytes) -> Optional[dict[str, Any]]: ...
    def put(self, obj: dict[str, Any]) -> tuple[bool, str]:
        """Verify and store. (created, "") or (False, error); a duplicate is (False, "")."""
        ...
    def owner_of(self, serial: int) -> Optional[str]: ...


def held_scopes(objects: "ObjectSet", interests: list[str]) -> list[str]:
    """Scopes of what this node holds beyond its own interests (carried
    for others). Nodes that take everything don't list it."""
    if "*" in interests:
        return []
    out: list[str] = []
    for oid in objects.oids("*"):
        obj = objects.get(oid) or {}
        if wants(interests, obj):
            continue
        for person in sorted(parties(obj)):
            if f"u:{person}" not in out:
                out.append(f"u:{person}")
    return out


# -- responder (every node) ------------------------------------------------------------


class SyncResponder:
    def __init__(self, objects: ObjectSet, *, role: str, interests: Callable[[], list[str]]) -> None:
        self.objects = objects
        self.role = role
        self.interests = interests

    async def handle_rpc(self, env: Envelope) -> Envelope:
        p = env.payload if isinstance(env.payload, dict) else {}

        def err(code: str) -> Envelope:
            return env.make_response(op=env.op, payload={"error": code}, error=True)

        if env.op == OP_HELLO:
            mine = self.interests()
            return env.make_response(
                op=env.op, payload={"r": self.role, "i": mine, "h": held_scopes(self.objects, mine)}
            )
        if env.op == OP_SUM:
            scope, prefix = str(p.get("q") or ""), str(p.get("p") or "").lower()
            if not scope or any(c not in "0123456789abcdef" for c in prefix):
                return err("invalid_payload")
            return env.make_response(op=env.op, payload=summarize(self.objects.oids(scope), prefix))
        if env.op == OP_WANT:
            oid = p.get("o")
            obj = self.objects.get(bytes(oid)) if isinstance(oid, bytes) else None
            if not obj:
                return env.make_response(op=env.op, payload={"missing": True})
            return env.make_response(op=env.op, payload=to_wire(obj))
        if env.op == OP_PUT:
            obj = from_wire(p, self.objects.owner_of)
            if obj is None:
                return err("unknown_certificate")
            created, code = self.objects.put(obj)
            if code:
                return err(code)
            return env.make_response(op=env.op, payload={"ok": True, "new": created})
        return err(f"unknown_op:{env.op}")


# -- initiator ---------------------------------------------------------------------------

Request = Callable[[str, dict[str, Any]], Awaitable[Optional[Envelope]]]


@dataclass
class SyncResult:
    pulled: int = 0
    pushed: int = 0
    rejected: list[str] = field(default_factory=list)
    requests: int = 0
    ok: bool = True


async def sync_with(
    request: Request, objects: ObjectSet, *, role: str, interests: list[str]
) -> SyncResult:
    """Reconcile with one peer: pull what we want and lack, push what it
    wants and lacks. ``request(op, payload)`` returns the reply (None when
    the peer didn't answer — the sync just stops; nothing is lost, the next
    meeting carries on)."""
    res = SyncResult()

    async def ask(op: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        res.requests += 1
        reply = await request(op, payload)
        if reply is None:
            res.ok = False
            return None
        return reply.payload if isinstance(reply.payload, dict) else {}

    hello = await ask(OP_HELLO, {"r": role, "i": interests, "h": held_scopes(objects, interests)})
    if hello is None:
        return res
    theirs = [str(q) for q in hello.get("i") or []]
    their_held = [str(q) for q in hello.get("h") or []]

    def pull_ok(scope: str) -> bool:
        return "*" in interests or scope in interests

    def push_ok(scope: str) -> bool:
        return "*" in theirs or scope in theirs

    # Scopes to reconcile: everything either side wants or holds, made
    # concrete. "*" is walked only between two take-everything nodes.
    if "*" in interests and "*" in theirs:
        scopes = ["*"]
    else:
        scopes = []
        for q in interests + theirs + held_scopes(objects, interests) + their_held:
            if q != "*" and q not in scopes:
                scopes.append(q)
    scopes = [q for q in scopes if pull_ok(q) or push_ok(q)]

    pull: set[bytes] = set()
    push: set[bytes] = set()

    async def walk(scope: str, prefix: str) -> bool:
        mine = under(objects.oids(scope), prefix)
        r = await ask(OP_SUM, {"q": scope, "p": prefix})
        if r is None or "n" not in r:
            return False
        if r["n"] == len(mine) and bytes(r["x"]) == fingerprint(mine):
            return True
        if "oids" in r:
            their_set = {bytes(o) for o in r["oids"]}
            if pull_ok(scope):
                pull.update(their_set - set(mine))
            if push_ok(scope):
                push.update(set(mine) - their_set)
            return True
        for digit, (n, x) in zip("0123456789abcdef", r["sub"]):
            child = under(mine, prefix + digit)
            if n == len(child) and bytes(x) == fingerprint(child):
                continue
            if n == 0:
                if push_ok(scope):
                    push.update(child)  # they have nothing here: no need to ask
                continue
            if not len(child) and not pull_ok(scope):
                continue
            if not await walk(scope, prefix + digit):
                return False
        return True

    for scope in scopes:
        if not await walk(scope, ""):
            return res

    want_mine = interests
    for oid in sorted(pull):
        r = await ask(OP_WANT, {"o": oid})
        if r is None:
            return res
        obj = None if r.get("missing") else from_wire(r, objects.owner_of)
        if obj is None or not wants(want_mine, obj):
            continue
        created, code = objects.put(obj)
        if code:
            res.rejected.append(code)
        elif created:
            res.pulled += 1

    for oid in sorted(push):
        obj = objects.get(oid)
        if not obj or not (wants(theirs, obj)):
            continue
        r = await ask(OP_PUT, to_wire(obj))
        if r is None:
            return res
        if r.get("error"):
            res.rejected.append(str(r["error"]))
        elif r.get("new"):
            res.pushed += 1
    return res


def max_signed_body(target: str, *, room: bool = False) -> int:
    """The longest body (bytes) a signed message to ``target`` (a username,
    or a conversation id when ``room``) may have so that it fits one packet
    in every form it travels in: signed MSG_SEND to Station, sync PUT, and
    a WANT reply, between devices with the longest node ids. The Scout's
    compose limit computes the same (firmware/pocket/src/app_dispatch.cpp)."""
    from shared.protocol.envelope import encode_cbor
    from shared.protocol.radio import RADIO_MDU

    node = "pocket-1-xxxx"
    addr = {"v": target} if room else {"p": target}

    def forms(n: int):
        body = "x" * n
        yield Envelope(mid="0" * 16, rid="0" * 16, src=node, dst="station", svc="DISPATCH",
                       op="MSG_SEND", flags=1, ts=4_000_000_000,
                       payload={**addr, "b": body, "o": bytes(16), "c": 0xFFFFFFFF, "s": bytes(64)})
        wire = {"o": bytes(16), "c": 0xFFFFFFFF, "b": body, "t": 4_000_000_000, "s": bytes(64), **addr}
        yield Envelope(mid="0" * 16, rid="0" * 16, src=node, dst=node, svc=SVC_SYNC, op=OP_PUT,
                       flags=1, ts=4_000_000_000, payload=wire)
        yield Envelope(mid="0" * 16, rid="0" * 16, src=node, dst=node, svc=SVC_SYNC, op=OP_WANT,
                       flags=2, ts=4_000_000_000, payload=wire)

    for n in range(140, 0, -1):
        if all(len(encode_cbor(e)) <= RADIO_MDU for e in forms(n)):
            return n
    return 0
