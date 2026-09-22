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
from server.services.dispatch.constants import (
    OP_MSG_ACK,
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
    OP_MSG_SYNC,
)
from server.services.dispatch.peer import PeerDispatchNode
from server.services.dispatch.service import DispatchService
from server.services.dispatch.store import DispatchStore
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import SVC_DISPATCH, Envelope, Flags


def _cfg(seed: int) -> MockTransportConfig:
    return MockTransportConfig(latency_ms_min=1, latency_ms_max=5, seed=seed)


def _memory_store() -> DispatchStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return DispatchStore(conn)


def _station(
    mesh: MockMesh, store: DispatchStore | None = None
) -> tuple[DispatchService, WaylinkGateway]:
    dispatch = DispatchService(store or _memory_store())
    transport = mesh.attach("station", _cfg(1))
    gateway = WaylinkGateway(transport, local_id="station")
    for op in (OP_MSG_SEND, OP_MSG_LIST, OP_MSG_ACK, OP_MSG_SYNC, OP_MSG_PUSH):
        gateway.register(SVC_DISPATCH, op, dispatch.handle_rpc)

    loop = asyncio.get_event_loop()
    dispatch.set_radio_push(lambda env: loop.create_task(gateway.send_envelope(env)))
    return dispatch, gateway


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
    dispatch, station_gateway = _station(mesh)
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
    dispatch, station_gateway = _station(mesh)
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
    dispatch, station_gateway = _station(mesh)
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
    dispatch, station_gateway = _station(mesh)
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
    dispatch, station_gateway = _station(mesh, store)
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
