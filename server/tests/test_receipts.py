"""Delivery receipts as signed objects (dispatch.rcpt, roadmap D4).

The recipient's device signs a receipt when a message lands; it travels by
peer sync like the message, so the sender learns "delivered" whichever way
it went — through Station, or Scout to Scout with no Station at all — and
Station marks the message DELIVERED when one reaches it.

The pinned receipt vector is also checked by the Scout at boot
(firmware/common/waypost_core wp::self_test)."""

from __future__ import annotations

import pytest

from server.services.dispatch.constants import DELIVERY_DELIVERED
from server.services.identity import certs as C
from server.services.identity import objects as O
from server.services.sync.engine import OP_PUT, SVC_SYNC, SyncResponder, to_wire
from shared.protocol.envelope import Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

from server.tests.test_peer_sync import World  # the same simulated network


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


def receipts(node) -> list[dict]:
    return [o for o in node.objects.objects.values() if O.is_receipt(o)]


def messages(node) -> list[dict]:
    return [o for o in node.objects.objects.values() if not O.is_receipt(o)]


async def test_receipt_reaches_station_and_the_sender(world):
    a, b = world.scout("pocket-1-aaaa"), world.scout("pocket-1-bbbb", seed=3)
    await a.start(), await b.start()
    gw = await world.station()
    try:
        world.mesh.link(a.node_id, "station")
        world.mesh.link(b.node_id, "station")
        msg = a.write("tents are up", peer="basecamp")
        assert (await a.sync("station")).pushed == 1
        assert world.db.dispatch.get_message(msg["o"].hex())["delivery_state"] != DELIVERY_DELIVERED

        assert (await b.sync("station")).pulled == 1
        (got,) = messages(b)
        b.acknowledge(got)
        r = await b.sync("station")
        assert r.pushed == 1 and not r.rejected
        assert world.db.dispatch.get_message(msg["o"].hex())["delivery_state"] == DELIVERY_DELIVERED

        r = await a.sync("station")
        assert r.pulled == 1
        (rcpt,) = receipts(a)
        assert rcpt["m"] == msg["o"] and rcpt["u"] == "basecamp"
        again = await a.sync("station")
        assert (again.pulled, again.pushed) == (0, 0)
    finally:
        await a.stop(), await b.stop(), await gw.stop()


async def test_receipt_without_station(world):
    a, b = world.scout("pocket-1-aaaa"), world.scout("pocket-1-bbbb", seed=3)
    world.mesh.link(a.node_id, b.node_id)
    await a.start(), await b.start()
    try:
        msg = a.write("meet at the bridge", peer="basecamp")
        assert (await b.sync(a.node_id)).pulled == 1
        b.acknowledge(messages(b)[0])
        r = await a.sync(b.node_id)
        assert r.pulled == 1 and receipts(a)[0]["m"] == msg["o"]
    finally:
        await a.stop(), await b.stop()


def signed_receipt(world, node, msg_oid, conv, *, oid=None, user=None):
    user = user or {"pocket-1-aaaa": "ridgeline", "pocket-1-bbbb": "basecamp", "pocket-1-cccc": "carol"}[node]
    obj = {"k": O.KIND_DISPATCH_RCPT, "o": oid or O.receipt_oid(msg_oid, user), "u": user,
           "a": world.ids[node], "v": conv, "m": msg_oid, "t": 1_791_000_100}
    obj["s"] = world.keys[node].sign(O.canonical_bytes(obj))
    return obj


async def test_bad_receipts_are_refused(world):
    responder = SyncResponder(world.station_set, role="station", interests=lambda: ["*"])

    async def put(obj):
        env = Envelope(src="pocket-1-cccc", dst="station", svc=SVC_SYNC, op=OP_PUT, flags=int(Flags.REQUEST),
                       payload=to_wire(obj))
        return (await responder.handle_rpc(env)).payload

    conv = "dm:basecamp:ridgeline"
    m = O.new_oid()
    # Someone outside the conversation can't confirm delivery.
    assert (await put(signed_receipt(world, "pocket-1-cccc", m, conv)))["error"] == "bad_signature"
    # The id must be the derived one (one receipt per person per message).
    assert (await put(signed_receipt(world, "pocket-1-bbbb", m, conv, oid=O.new_oid())))["error"] == "invalid_payload"
    # Altered in transit.
    r = signed_receipt(world, "pocket-1-bbbb", m, conv)
    r["m"] = O.new_oid()
    assert (await put(r))["error"] == "bad_signature"
    # A genuine one is kept once.
    good = signed_receipt(world, "pocket-1-bbbb", m, conv)
    assert (await put(good)) == {"ok": True, "new": True}
    assert (await put(good)) == {"ok": True, "new": False}


async def test_receipt_before_its_message(world):
    """A receipt can overtake its message (different paths): it counts once
    the message arrives."""
    a = world.scout("pocket-1-aaaa")
    msg = a.write("the van leaves at 6", peer="basecamp")
    rcpt = signed_receipt(world, "pocket-1-bbbb", msg["o"], msg["v"])
    assert world.station_set.put(rcpt) == (True, "")
    assert world.station_set.put(dict(msg)) == (True, "")
    assert world.db.dispatch.get_message(msg["o"].hex())["delivery_state"] == DELIVERY_DELIVERED


def test_receipt_fits_one_packet(world):
    longest = "x" * 32
    obj = signed_receipt(world, "pocket-1-bbbb", O.new_oid(), "room:" + "r" * 40)
    for op in (OP_PUT, "WANT"):
        env = Envelope(src="pocket-1-" + longest[:8], dst="pocket-1-" + longest[:8], svc=SVC_SYNC, op=op,
                       flags=int(Flags.RESPONSE), payload=to_wire(obj))
        assert len(encode_cbor(env)) <= RADIO_MDU


# -- pinned vector (the Scout checks the same) -------------------------------------

VECTOR_RECEIPT = {"k": "dispatch.rcpt", "o": O.receipt_oid(bytes(range(16)), "bob"), "u": "bob",
                  "a": bytes(range(32, 48)), "v": "dm:aj:bob", "m": bytes(range(16)), "t": 1790000100}


def test_pinned_receipt_vector():
    assert VECTOR_RECEIPT["o"].hex() == VECTOR_RECEIPT_OID
    key = C.CommunityKey.from_seed(bytes(range(32)))  # same seed as the other vectors
    sig = key._private.sign(O.canonical_bytes(VECTOR_RECEIPT))
    assert sig.hex() == VECTOR_RECEIPT_SIG


VECTOR_RECEIPT_OID = "aff805e2718459f14c9dfeb9df130ae0"
VECTOR_RECEIPT_SIG = (
    "7a79b6f86b266cc608416c5c3948375c703c9ce3f3954dc1ea99906aebe4e3bc"
    "a9f95457d31d5a56769c72e2c09a0c692b6d11f6ab75c42adc9dac0c528f3802"
)
