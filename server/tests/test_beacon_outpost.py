"""Beacon propagation through Outposts — sim slice (BEACON_SYNC)."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from server.gateway.waylink import WaylinkGateway
from server.services.beacon.constants import OP_BEACON_SYNC
from server.services.beacon.service import BeaconService
from server.services.beacon.store import BeaconStore
from server.services.corkboard.store import CorkboardStore
from server.services.dispatch.outpost import OutpostNode
from server.services.dispatch.store import DispatchStore
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import SVC_BEACON


def _cfg(seed: int) -> MockTransportConfig:
    return MockTransportConfig(latency_ms_min=1, latency_ms_max=5, seed=seed)


def _memory_beacon(*, claimed: set[str] | None = None) -> BeaconService:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    claimed = claimed or set()
    return BeaconService(BeaconStore(conn), is_claimed_outpost=lambda n: n in claimed)


def _memory_store() -> DispatchStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return DispatchStore(conn)


def _memory_corkboard() -> CorkboardStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return CorkboardStore(conn)


def _station_with_beacon(
    mesh: MockMesh, *, claimed: set[str] | None = None
) -> tuple[BeaconService, WaylinkGateway]:
    beacon = _memory_beacon(claimed=claimed)
    transport = mesh.attach("station", _cfg(1))
    gateway = WaylinkGateway(transport, local_id="station")
    gateway.register(SVC_BEACON, OP_BEACON_SYNC, beacon.handle_rpc)
    return beacon, gateway


def _outpost(mesh: MockMesh, node_id: str, seed: int) -> OutpostNode:
    transport = mesh.attach(node_id, _cfg(seed))
    return OutpostNode(
        node_id=node_id,
        transport=transport,
        store=_memory_store(),
        corkboard_store=_memory_corkboard(),
    )


@pytest.mark.asyncio
async def test_outpost_sync_caches_station_active_beacon():
    mesh = MockMesh()
    beacon, gateway = _station_with_beacon(mesh, claimed={"outpost-ridge"})
    o = _outpost(mesh, "outpost-ridge", 80)
    mesh.link("outpost-ridge", "station")
    beacon.push(
        author="aj",
        title="Wildfire smoke",
        body="Air quality poor — limit outdoor activity.",
        bypass_cooldown=True,
    )
    await gateway.start()
    await o.start()
    try:
        assert o.get_cached_beacon() is None
        result = await o.sync_beacon()
        assert result["ok"] is True
        assert result["active"]["title"] == "Wildfire smoke"
        assert o.get_cached_beacon()["title"] == "Wildfire smoke"
    finally:
        await gateway.stop()
        await o.stop()


@pytest.mark.asyncio
async def test_outpost_relay_push_reaches_station_on_sync():
    mesh = MockMesh()
    beacon, gateway = _station_with_beacon(mesh, claimed={"outpost-ridge"})
    o = _outpost(mesh, "outpost-ridge", 81)
    mesh.link("outpost-ridge", "station")
    await gateway.start()
    await o.start()
    try:
        # A walk-up author claim in the payload is content, not identity —
        # the beacon of record is attributed to the (claimed) outpost, never
        # to whatever free-text name the relayed event happens to carry.
        o.queue_beacon_push(
            author="bob",
            title="Injury on trail",
            body="Need medics at mile 4.",
            mid="relay-mid-1",
        )
        result = await o.sync_beacon()
        assert result["ok"] is True
        assert result["ingested"] == 1
        active = beacon.get_active()
        assert active is not None
        assert active["title"] == "Injury on trail"
        assert active["author"] == "outpost:outpost-ridge"
        assert o.get_cached_beacon()["id"] == active["id"]
    finally:
        await gateway.stop()
        await o.stop()


@pytest.mark.asyncio
async def test_unclaimed_outpost_sync_is_rejected():
    mesh = MockMesh()
    # No outposts in the claimed set — "outpost-rogue" is a stand-in for
    # anything that sends a BEACON_SYNC packet without ever having gone
    # through OUTPOST_CLAIM (the same bar BEACON_PUSH/CLEAR already hold
    # a paired Pocket to via device binding).
    beacon, gateway = _station_with_beacon(mesh, claimed=set())
    o = _outpost(mesh, "outpost-rogue", 84)
    mesh.link("outpost-rogue", "station")
    await gateway.start()
    await o.start()
    try:
        o.queue_beacon_push(
            author="aj",
            title="Fake evacuation order",
            body="Impersonation attempt.",
            mid="relay-mid-spoof",
        )
        result = await o.sync_beacon()
        assert result["ok"] is False
        assert beacon.get_active() is None
        # Queue is untouched on rejection — nothing was silently dropped,
        # a legitimately claimed retry later can still deliver it.
        assert len(o._beacon_pending) == 1
    finally:
        await gateway.stop()
        await o.stop()


@pytest.mark.asyncio
async def test_outpost_sync_clear_updates_local_cache():
    mesh = MockMesh()
    beacon, gateway = _station_with_beacon(mesh, claimed={"outpost-ridge"})
    o = _outpost(mesh, "outpost-ridge", 82)
    mesh.link("outpost-ridge", "station")
    created = beacon.push(
        author="aj",
        title="Temporary siren test",
        body="Ignore.",
        bypass_cooldown=True,
    )
    await gateway.start()
    await o.start()
    try:
        await o.sync_beacon()
        assert o.get_cached_beacon() is not None

        beacon.clear(created["id"])
        result = await o.sync_beacon()
        assert result["ok"] is True
        assert o.get_cached_beacon() is None
    finally:
        await gateway.stop()
        await o.stop()


@pytest.mark.asyncio
async def test_outpost_beacon_resync_is_idempotent():
    mesh = MockMesh()
    beacon, gateway = _station_with_beacon(mesh, claimed={"outpost-ridge"})
    o = _outpost(mesh, "outpost-ridge", 83)
    mesh.link("outpost-ridge", "station")
    await gateway.start()
    await o.start()
    try:
        o.queue_beacon_push(
            author="carol",
            title="Bridge out",
            body="Use the ford.",
            mid="relay-mid-dup",
        )
        first = await o.sync_beacon()
        assert first["ok"] is True
        assert beacon.get_active()["title"] == "Bridge out"

        # Pending queue cleared — second sync uploads nothing new.
        second = await o.sync_beacon()
        assert second["ok"] is True
        assert second["uploaded"] == 0
        assert beacon.get_active()["title"] == "Bridge out"
    finally:
        await gateway.stop()
        await o.stop()
