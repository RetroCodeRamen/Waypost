"""M3 slice — peer-to-peer Dispatch without Station + carry-forward MSG_SYNC.

Proves, in the mock mesh (sim-first per docs/roadmap.md M3):
  1. Direct peer -> peer delivery works with no Station node in the mesh.
  2. A peer that can't reach its target yet queues locally, then delivers
     once a link appears (courier-style retry, mirrors N1's Station-side
     bind-time flush but on the peer).
  3. A courier syncs a locally-delivered copy to Station via MSG_SYNC;
     dedup by mid keeps a resync idempotent.
  4. Station piggybacks its own pending queue for a user back to the
     courier in the same MSG_SYNC round trip.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from server.gateway.waylink import WaylinkGateway
from server.services.corkboard.constants import OP_BOARD_SYNC
from server.services.corkboard.service import CorkboardService
from server.services.corkboard.store import CorkboardStore
from server.services.dispatch.constants import (
    OP_MSG_ACK,
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
    OP_MSG_SYNC,
)
from server.services.dispatch.outpost import OutpostNode
from server.services.dispatch.peer import (
    COURIER_TTL_SECONDS,
    MAX_COURIER_HOPS,
    PeerDispatchNode,
)
from server.services.dispatch.service import DispatchService
from server.services.dispatch.store import DispatchStore
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import SVC_CORKBOARD, SVC_DISPATCH, Envelope, Flags


def _cfg(seed: int) -> MockTransportConfig:
    return MockTransportConfig(latency_ms_min=1, latency_ms_max=5, seed=seed)


def _memory_store() -> DispatchStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return DispatchStore(conn)


def _station(
    mesh: MockMesh, store: DispatchStore | None = None
) -> tuple[DispatchService, WaylinkGateway, CorkboardService]:
    dispatch = DispatchService(store or _memory_store())
    corkboard = CorkboardService(_memory_corkboard_store())
    transport = mesh.attach("station", _cfg(1))
    gateway = WaylinkGateway(transport, local_id="station")
    for op in (OP_MSG_SEND, OP_MSG_LIST, OP_MSG_ACK, OP_MSG_SYNC, OP_MSG_PUSH):
        gateway.register(SVC_DISPATCH, op, dispatch.handle_rpc)
    gateway.register(SVC_CORKBOARD, OP_BOARD_SYNC, corkboard.handle_rpc)

    loop = asyncio.get_event_loop()
    dispatch.set_radio_push(lambda env: loop.create_task(gateway.send_envelope(env)))
    return dispatch, gateway, corkboard


async def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


def _bodies(peer: PeerDispatchNode) -> list[str]:
    return [
        m["body"]
        for conv in peer.store.list_conversations(peer.username)
        for m in peer.store.list_messages(conv["id"])
    ]


def _peer(mesh: MockMesh, node_id: str, username: str, seed: int) -> PeerDispatchNode:
    store = _memory_store()
    transport = mesh.attach(node_id, _cfg(seed))
    return PeerDispatchNode(node_id=node_id, username=username, transport=transport, store=store)


def _memory_corkboard_store() -> CorkboardStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return CorkboardStore(conn)


def _outpost(
    mesh: MockMesh, node_id: str, seed: int, *, display_name: str | None = None
) -> OutpostNode:
    store = _memory_store()
    transport = mesh.attach(node_id, _cfg(seed))
    return OutpostNode(
        node_id=node_id,
        transport=transport,
        store=store,
        corkboard_store=_memory_corkboard_store(),
        display_name=display_name,
    )


@pytest.mark.asyncio
async def test_peer_to_peer_without_station():
    mesh = MockMesh()
    a = _peer(mesh, "radio-aj", "aj", 2)
    b = _peer(mesh, "radio-bob", "bob", 3)
    mesh.link("radio-aj", "radio-bob")  # no station node exists at all
    await a.start()
    await b.start()
    try:
        msg = await a.send_direct(
            peer_username="bob", peer_node_id="radio-bob", body="at the outpost"
        )
        assert msg["delivery_state"] == "ROUTED"

        bob_msgs = [
            m
            for conv in b.store.list_conversations("bob")
            for m in b.store.list_messages(conv["id"])
        ]
        assert any(m["body"] == "at the outpost" and m["sender"] == "aj" for m in bob_msgs)
    finally:
        await a.stop()
        await b.stop()


@pytest.mark.asyncio
async def test_queue_then_flush_when_peer_appears():
    mesh = MockMesh()
    a = _peer(mesh, "radio-aj", "aj", 4)
    b = _peer(mesh, "radio-bob", "bob", 5)
    # MockMesh treats a fully link-less mesh as all-reachable (fallback for
    # simple tests) — mark bob explicitly out of range until it "appears".
    mesh.set_connected("radio-bob", False)
    await a.start()
    await b.start()
    try:
        msg = await a.send_direct(
            peer_username="bob", peer_node_id="radio-bob", body="on my way"
        )
        assert msg["delivery_state"] == "SENT"
        assert len(a.store.list_courier_pending("radio-bob")) == 1

        mesh.set_connected("radio-bob", True)
        mesh.link("radio-aj", "radio-bob")
        flushed = await a.flush_pending("radio-bob")
        assert flushed == 1
        assert a.store.list_courier_pending("radio-bob") == []

        bob_msgs = [
            m
            for conv in b.store.list_conversations("bob")
            for m in b.store.list_messages(conv["id"])
        ]
        assert any(m["body"] == "on my way" for m in bob_msgs)
    finally:
        await a.stop()
        await b.stop()


@pytest.mark.asyncio
async def test_carry_forward_sync_to_station_dedups():
    mesh = MockMesh()
    dispatch, station_gateway, _corkboard = _station(mesh)
    b = _peer(mesh, "radio-bob", "bob", 6)
    dispatch.store.bind_device("radio-bob", "bob")
    mesh.link("radio-bob", "station")
    await station_gateway.start()
    await b.start()
    try:
        conv = b.store.ensure_direct("bob", "aj")
        b.store.add_message(
            conversation_id=conv["id"],
            sender="aj",
            body="need water",
            delivery_state="DELIVERED",
        )
        b.store.queue_courier(
            b.store.list_messages(conv["id"])[0]["id"], "station"
        )
        assert len(b.store.list_courier_pending("station")) == 1

        result = await b.sync_with_station()
        assert result["ok"] is True
        assert result["synced"] == 1
        assert b.store.list_courier_pending("station") == []

        station_msgs = dispatch.store.list_messages(conv["id"])
        assert any(m["body"] == "need water" for m in station_msgs)

        result2 = await b.sync_with_station()
        assert result2["synced"] == 0
        station_msgs2 = dispatch.store.list_messages(conv["id"])
        assert sum(1 for m in station_msgs2 if m["body"] == "need water") == 1
    finally:
        await station_gateway.stop()
        await b.stop()


@pytest.mark.asyncio
async def test_sync_piggybacks_station_pending():
    mesh = MockMesh()
    dispatch, station_gateway, _corkboard = _station(mesh)
    b = _peer(mesh, "radio-bob", "bob", 7)
    mesh.link("radio-bob", "station")
    await station_gateway.start()
    await b.start()
    try:
        # AJ messaged Bob over the portal while Bob had no bound Pocket yet.
        dispatch.send_direct(sender="aj", peer="bob", body="dinner at 6", transport="wifi")
        assert dispatch.sync_status()["pending_dispatch"] == 1

        # Bind only when the Pocket comes online to sync.
        dispatch.store.bind_device("radio-bob", "bob")
        result = await b.sync_with_station()
        assert result["ok"] is True
        assert result["received"] == 1

        bob_msgs = [
            m
            for conv in b.store.list_conversations("bob")
            for m in b.store.list_messages(conv["id"])
        ]
        assert any(m["body"] == "dinner at 6" for m in bob_msgs)
        assert dispatch.sync_status()["pending_dispatch"] == 0
    finally:
        await station_gateway.stop()
        await b.stop()


@pytest.mark.asyncio
async def test_sync_rejects_unbound_courier():
    mesh = MockMesh()
    dispatch, station_gateway, _corkboard = _station(mesh)
    b = _peer(mesh, "radio-bob", "bob", 8)
    # Intentionally no bind_device — must fail closed
    mesh.link("radio-bob", "station")
    await station_gateway.start()
    await b.start()
    try:
        result = await b.sync_with_station()
        assert result["ok"] is False
    finally:
        await station_gateway.stop()
        await b.stop()


@pytest.mark.asyncio
async def test_multihop_courier_aj_bob_carol():
    """aj -- bob -- carol: aj cannot one-hop carol; bob carries the message."""
    mesh = MockMesh()
    a = _peer(mesh, "radio-aj", "aj", 9)
    b = _peer(mesh, "radio-bob", "bob", 10)
    c = _peer(mesh, "radio-carol", "carol", 11)
    mesh.link("radio-aj", "radio-bob")
    mesh.link("radio-bob", "radio-carol")
    # No aj—carol link. Transport BFS would be 2 hops; peer only pushes 1 hop.
    await a.start()
    await b.start()
    await c.start()
    try:
        msg = await a.send_direct(
            peer_username="carol",
            peer_node_id="radio-carol",
            body="via bob please",
        )
        assert msg["delivery_state"] == "SENT"
        assert len(a.store.list_courier_pending("radio-carol")) == 1

        handed = await a.handoff_to("radio-bob")
        assert handed == 1
        assert a.store.list_courier_pending("radio-carol") == []
        assert len(b.store.list_courier_pending("radio-carol")) == 1

        # Carol has not seen it yet
        carol_before = [
            m
            for conv in c.store.list_conversations("carol")
            for m in c.store.list_messages(conv["id"])
        ]
        assert not any(m["body"] == "via bob please" for m in carol_before)

        flushed = await b.flush_pending("radio-carol")
        assert flushed == 1

        carol_msgs = [
            m
            for conv in c.store.list_conversations("carol")
            for m in c.store.list_messages(conv["id"])
        ]
        assert any(
            m["body"] == "via bob please" and m["sender"] == "aj" for m in carol_msgs
        )
    finally:
        await a.stop()
        await b.stop()
        await c.stop()


@pytest.mark.asyncio
async def test_wifi_to_lora_failover_same_conversation():
    """Bob's Pocket has a Wi‑Fi binding (HTTP outbox) and a LoRa binding.

    Wi‑Fi drops mid-conversation: his retry over LoRa must not duplicate, the
    portal reply must reach him over LoRa, and the stale Wi‑Fi copy must not
    be redelivered when Wi‑Fi comes back.
    """
    mesh = MockMesh()
    dispatch, station_gateway, _corkboard = _station(mesh)
    bob = _peer(mesh, "radio-bob", "bob", 12)
    mesh.link("radio-bob", "station")
    dispatch.store.ensure_direct("aj", "bob")
    dispatch.bind_device("pocket-bob", "bob")  # Wi‑Fi path
    dispatch.bind_device("radio-bob", "bob")  # LoRa path
    await station_gateway.start()
    await bob.start()
    try:
        # 1) Bob sends over Wi‑Fi (what POST /api/waylink/rpc does).
        wifi_send = Envelope(
            src="pocket-bob",
            dst="station",
            svc=SVC_DISPATCH,
            op=OP_MSG_SEND,
            flags=int(Flags.REQUEST),
            payload={"peer": "aj", "body": "heading out", "message_id": "mid-heading-out"},
        )
        r1 = await dispatch.handle_rpc(wifi_send)
        assert r1.payload["created"] is True

        # 2) Wi‑Fi drops before Bob saw the ACK; his Pocket retries over LoRa.
        lora_retry = Envelope(
            src="radio-bob",
            dst="station",
            svc=SVC_DISPATCH,
            op=OP_MSG_SEND,
            flags=int(Flags.REQUEST),
            payload={"peer": "aj", "body": "heading out", "message_id": "mid-heading-out"},
        )
        r2 = await bob.request(lora_retry)
        assert r2 is not None and r2.payload["created"] is False
        conv_id = r1.payload["conversation_id"]
        assert [m["body"] for m in dispatch.list_messages(conv_id)].count("heading out") == 1

        # 3) AJ replies from the portal; only LoRa can reach Bob now.
        sent = dispatch.send_direct(sender="aj", peer="bob", body="stay safe")
        mid = sent["message"]["id"]
        assert sent["message"]["delivery_state"] == "SENT"
        bob_pending = lambda: dispatch.sync_status()["pending_by_user"].get("bob", 0)  # noqa: E731
        assert bob_pending() == 1

        assert await _wait_for(lambda: "stay safe" in _bodies(bob))
        assert await _wait_for(lambda: bob_pending() == 0)
        state = next(m for m in dispatch.list_messages(conv_id) if m["id"] == mid)
        assert state["delivery_state"] == "DELIVERED"

        # 4) Wi‑Fi returns: the copy confirmed over LoRa is not redelivered.
        assert dispatch.poll_outbox("pocket-bob") == []
    finally:
        await station_gateway.stop()
        await bob.stop()


@pytest.mark.asyncio
async def test_pending_survives_restart_and_fails_over_to_lora():
    """Bob is bound on Wi‑Fi but out of range; Station restarts; his LoRa
    Pocket binds later and still gets the message."""
    store = _memory_store()
    before = DispatchService(store)
    store.ensure_direct("aj", "bob")
    before.bind_device("pocket-bob", "bob")
    sent = before.send_direct(sender="aj", peer="bob", body="radio check at 9")
    assert sent["message"]["delivery_state"] == "SENT"
    # Never polled — Bob walked out of Wi‑Fi range. Station restarts (memory lost).
    del before

    mesh = MockMesh()
    dispatch, station_gateway, _corkboard = _station(mesh, store)
    bob = _peer(mesh, "radio-bob", "bob", 13)
    mesh.link("radio-bob", "station")
    await station_gateway.start()
    await bob.start()
    try:
        assert dispatch.sync_status()["pending_dispatch"] == 1
        flushed = dispatch.bind_device("radio-bob", "bob")["flushed"]
        assert flushed == 1
        assert await _wait_for(lambda: "radio check at 9" in _bodies(bob))
        assert await _wait_for(lambda: dispatch.sync_status()["pending_dispatch"] == 0)
    finally:
        await station_gateway.stop()
        await bob.stop()


@pytest.mark.asyncio
async def test_hop_cap_blocks_relay_beyond_three_devices():
    """aj -- b1 -- b2 -- b3 -- b4, no route to the recipient at all.

    Each handoff is one hop between travel devices. MAX_COURIER_HOPS (3)
    should allow aj->b1->b2->b3 (3 hops) but refuse to relay b3->b4 (a 4th
    device-to-device hop) — the message stays parked at b3 instead.
    """
    assert MAX_COURIER_HOPS == 3
    mesh = MockMesh()
    aj = _peer(mesh, "radio-aj", "aj", 20)
    b1 = _peer(mesh, "radio-b1", "carrier1", 21)
    b2 = _peer(mesh, "radio-b2", "carrier2", 22)
    b3 = _peer(mesh, "radio-b3", "carrier3", 23)
    b4 = _peer(mesh, "radio-b4", "carrier4", 24)
    mesh.attach("radio-zoe", _cfg(25))  # recipient exists but is unreachable
    mesh.link("radio-aj", "radio-b1")
    mesh.link("radio-b1", "radio-b2")
    mesh.link("radio-b2", "radio-b3")
    mesh.link("radio-b3", "radio-b4")
    nodes = [aj, b1, b2, b3, b4]
    for n in nodes:
        await n.start()
    try:
        msg = await aj.send_direct(
            peer_username="zoe", peer_node_id="radio-zoe", body="no route to zoe"
        )
        assert msg["delivery_state"] == "SENT"

        assert await aj.handoff_to("radio-b1") == 1
        assert (b1.store.list_courier_pending("radio-zoe")[0]["hops"]) == 1

        assert await b1.handoff_to("radio-b2") == 1
        assert (b2.store.list_courier_pending("radio-zoe")[0]["hops"]) == 2

        assert await b2.handoff_to("radio-b3") == 1
        assert (b3.store.list_courier_pending("radio-zoe")[0]["hops"]) == 3

        # 4th device-to-device hop — capped, refused.
        assert await b3.handoff_to("radio-b4") == 0
        assert len(b3.store.list_courier_pending("radio-zoe")) == 1
        assert b4.store.list_courier_pending("radio-zoe") == []
    finally:
        for n in nodes:
            await n.stop()


@pytest.mark.asyncio
async def test_courier_entries_expire_after_ttl():
    mesh = MockMesh()
    a = _peer(mesh, "radio-aj", "aj", 26)
    conv = a.store.ensure_direct("aj", "bob")
    msg, _ = a.store.add_message(
        conversation_id=conv["id"], sender="aj", body="stale", delivery_state="SENT"
    )
    a.store.queue_courier(msg["id"], "radio-bob")

    # Backdate the row past the TTL directly (mirrors the pairing-code
    # expiry test style — no need to mock time.time()).
    a.store._conn.execute(
        "UPDATE courier_queue SET created_at = ? WHERE message_id = ?",
        (0.0, msg["id"]),
    )
    a.store._conn.commit()
    assert len(a.store.list_courier_pending("radio-bob")) == 1

    purged = a.store.purge_expired_courier(COURIER_TTL_SECONDS)
    assert purged == 1
    assert a.store.list_courier_pending("radio-bob") == []


@pytest.mark.asyncio
async def test_flush_pending_purges_stale_entries_opportunistically():
    """A node doesn't need an explicit purge call — flush_pending (and
    handoff_to) sweep stale courier entries as a side effect of normal use."""
    mesh = MockMesh()
    a = _peer(mesh, "radio-aj", "aj", 27)
    b = _peer(mesh, "radio-bob", "bob", 28)
    mesh.link("radio-aj", "radio-bob")
    await a.start()
    await b.start()
    try:
        conv = a.store.ensure_direct("aj", "carol")
        stale_msg, _ = a.store.add_message(
            conversation_id=conv["id"], sender="aj", body="old news", delivery_state="SENT"
        )
        a.store.queue_courier(stale_msg["id"], "radio-carol")
        a.store._conn.execute(
            "UPDATE courier_queue SET created_at = ? WHERE message_id = ?",
            (0.0, stale_msg["id"]),
        )
        a.store._conn.commit()

        await a.flush_pending("radio-bob")  # unrelated dest; purge still runs
        assert a.store.list_courier_pending("radio-carol") == []
    finally:
        await a.stop()
        await b.stop()


@pytest.mark.asyncio
async def test_outpost_route_cache_sticky_then_rediscovers_when_cleared():
    """Cache the discovered next hop toward Station and keep using it even
    once a shorter route appears (avoid constant re-discovery). When the
    cache is empty — which is what relay_toward_station does after a
    failed push, so a later attempt doesn't keep failing against a stale
    hop — the next call rediscovers via BFS.

    (MockMesh's BFS routing ignores `set_connected`/disconnection once a
    real adjacency link exists — that flag only matters in its no-links
    fallback path — so there's no fast way to simulate the cached hop
    itself going unreachable here; this covers the rediscovery mechanics
    that matter, not the push-failure trigger, which would need a real
    ~5s request timeout to exercise honestly.)"""
    mesh = MockMesh()
    o1 = _outpost(mesh, "outpost-1", 40)
    o2 = _outpost(mesh, "outpost-2", 41)
    mesh.attach("station", _cfg(42))
    mesh.link("outpost-1", "outpost-2")
    mesh.link("outpost-2", "station")
    await o1.start()
    await o2.start()
    try:
        assert await o1._route_to_station() == "outpost-2"
        assert o1._preferred_station_hop == "outpost-2"

        # A shorter path appears; cache should still win while it's usable.
        mesh.link("outpost-1", "station")
        assert await o1._route_to_station() == "outpost-2"

        # Cache cleared -> rediscovers, finds the now-available direct hop.
        o1._preferred_station_hop = None
        assert await o1._route_to_station() == "station"
    finally:
        await o1.stop()
        await o2.stop()


@pytest.mark.asyncio
async def test_outpost_relay_uncapped_beyond_travel_device_cap():
    """5 outposts relay a Station-bound message — more hops than
    MAX_COURIER_HOPS (3), proving OutpostNode relay is exempt from the cap
    that governs PeerDispatchNode.handoff_to."""
    assert MAX_COURIER_HOPS == 3
    mesh = MockMesh()
    dispatch, station_gateway, _corkboard = _station(mesh)
    outposts = [_outpost(mesh, f"outpost-{i}", 50 + i) for i in range(5)]
    chain = [o.node_id for o in outposts] + ["station"]
    for a, b in zip(chain, chain[1:]):
        mesh.link(a, b)
    await station_gateway.start()
    for o in outposts:
        await o.start()
    try:
        seed_msg, _ = outposts[0].store.add_message(
            conversation_id="test:seed",
            sender="aj",
            body="need resupply, 5 hops out",
            delivery_state="SENT",
        )
        outposts[0].store.queue_courier(seed_msg["id"], "station", for_user="bob")

        for o in outposts:
            assert await o.relay_toward_station() == 1

        conv = dispatch.store.get_conversation("dm:aj:bob")
        assert conv is not None
        msgs = dispatch.store.list_messages(conv["id"])
        assert any(m["body"] == "need resupply, 5 hops out" for m in msgs)
    finally:
        await station_gateway.stop()
        for o in outposts:
            await o.stop()


@pytest.mark.asyncio
async def test_outpost_direct_match_between_colocated_pockets():
    """Two Pockets both in range of the same Outpost — delivery happens
    via the Outpost's immediate hand-off, not a queued round trip."""
    mesh = MockMesh()
    aj = _peer(mesh, "radio-aj", "aj", 60)
    bob = _peer(mesh, "radio-bob", "bob", 61)
    o = _outpost(mesh, "outpost-x", 62)
    mesh.link("radio-aj", "outpost-x")
    mesh.link("outpost-x", "radio-bob")
    await aj.start()
    await bob.start()
    await o.start()
    try:
        await aj.send_direct(
            peer_username="bob", peer_node_id="radio-bob", body="right here?"
        )
        assert len(aj.store.list_courier_pending("radio-bob")) == 1

        assert await aj.handoff_to("outpost-x") == 1

        assert await _wait_for(lambda: "right here?" in _bodies(bob))
        # Delivered directly through the outpost — never sat in its queue.
        assert o.store.list_courier_pending("radio-bob") == []
    finally:
        await aj.stop()
        await bob.stop()
        await o.stop()


@pytest.mark.asyncio
async def test_outpost_syncs_local_notes_to_station_and_resync_is_idempotent():
    mesh = MockMesh()
    dispatch, station_gateway, corkboard = _station(mesh)
    o = _outpost(mesh, "outpost-ridge", 70, display_name="Ridge Trailhead")
    mesh.link("outpost-ridge", "station")
    await station_gateway.start()
    await o.start()
    try:
        o.add_local_note(body="Bear near the creek", signature="-Jamie")
        assert len(o.corkboard_store.list_unsynced("outpost-ridge")) == 1

        result = await o.sync_corkboard()
        assert result["ok"] is True
        assert result["synced"] == 1
        assert o.corkboard_store.list_unsynced("outpost-ridge") == []

        station_notes = corkboard.list_notes("outpost-ridge")
        assert any(n["body"] == "Bear near the creek" for n in station_notes)
        outposts = corkboard.list_outposts()
        assert any(
            row["node_id"] == "outpost-ridge" and row["display_name"] == "Ridge Trailhead"
            for row in outposts
        )

        # Nothing new locally -> idempotent resync.
        result2 = await o.sync_corkboard()
        assert result2["synced"] == 0
        assert sum(1 for n in corkboard.list_notes("outpost-ridge") if n["body"] == "Bear near the creek") == 1
    finally:
        await station_gateway.stop()
        await o.stop()


@pytest.mark.asyncio
async def test_outpost_sync_receives_piggybacked_station_note():
    mesh = MockMesh()
    dispatch, station_gateway, corkboard = _station(mesh)
    o = _outpost(mesh, "outpost-ridge", 71)
    mesh.link("outpost-ridge", "station")
    await station_gateway.start()
    await o.start()
    try:
        corkboard.post_note(
            outpost_id="outpost-ridge", body="Trail closed past mile 6", signature="Station"
        )

        result = await o.sync_corkboard()
        assert result["ok"] is True
        assert result["received"] == 1

        local_notes = o.corkboard_store.list_notes("outpost-ridge")
        assert any(n["body"] == "Trail closed past mile 6" for n in local_notes)
        # Arrived already-synced -- doesn't get re-uploaded next time.
        assert o.corkboard_store.list_unsynced("outpost-ridge") == []
    finally:
        await station_gateway.stop()
        await o.stop()
