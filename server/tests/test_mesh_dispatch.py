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
    OP_MSG_SEND,
    OP_MSG_SYNC,
)
from server.services.dispatch.peer import PeerDispatchNode
from server.services.dispatch.service import DispatchService
from server.services.dispatch.store import DispatchStore
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import SVC_DISPATCH


def _cfg(seed: int) -> MockTransportConfig:
    return MockTransportConfig(latency_ms_min=1, latency_ms_max=5, seed=seed)


def _memory_store() -> DispatchStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return DispatchStore(conn)


def _station(mesh: MockMesh) -> tuple[DispatchService, WaylinkGateway]:
    store = _memory_store()
    dispatch = DispatchService(store)
    transport = mesh.attach("station", _cfg(1))
    gateway = WaylinkGateway(transport, local_id="station")
    gateway.register(SVC_DISPATCH, OP_MSG_SEND, dispatch.handle_rpc)
    gateway.register(SVC_DISPATCH, OP_MSG_LIST, dispatch.handle_rpc)
    gateway.register(SVC_DISPATCH, OP_MSG_ACK, dispatch.handle_rpc)
    gateway.register(SVC_DISPATCH, OP_MSG_SYNC, dispatch.handle_rpc)

    loop = asyncio.get_event_loop()
    dispatch.set_radio_push(lambda env: loop.create_task(gateway.send_envelope(env)))
    return dispatch, gateway


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
        # AJ messaged Bob over the portal while Bob's Pocket was out of range.
        dispatch.send_direct(sender="aj", peer="bob", body="dinner at 6", transport="wifi")
        assert dispatch.sync_status()["pending_dispatch"] == 1

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
