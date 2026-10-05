"""Peer sync (roadmap D4) in the mock mesh: signed objects move between any
two nodes — Scout, courier, Station — with no realtime path, and converge.

Acceptance tests from docs/roadmap.md:
  T1  no Station: two Scouts still exchange messages (and a courier links islands)
  T2  Station returns: it reconciles everything that happened, nothing duplicated
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pytest
import RNS
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from server.api.db import Database
from server.gateway.waylink import WaylinkGateway
from server.services.dispatch.service import DispatchService
from server.services.identity import certs as C
from server.services.identity.objects import OfflineVerifier
from server.services.identity.service import IdentityService, waylink_dest_hex
from server.services.sync.engine import (
    max_signed_body,
    OP_HELLO,
    OP_PUT,
    OP_SUM,
    OP_WANT,
    SVC_SYNC,
    SyncResponder,
    sync_with,
)
from server.services.sync.node import SyncNode
from server.services.sync.sets import MemoryObjectSet, StationObjectSet
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

PEOPLE = {"pocket-1-aaaa": "ridgeline", "pocket-1-bbbb": "basecamp", "pocket-1-cccc": "carol"}


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.db = Database(tmp_path / "station.db")
        self.dispatch = DispatchService(self.db.dispatch,
                                        user_exists=lambda u: self.db.get_user_by_username(u) is not None)
        self.key = C.CommunityKey.generate()
        self.identity = IdentityService(self.db.identity, self.key, get_binding=self.db.dispatch.get_binding,
                                        get_user=self.db.get_user_by_username)
        self.dispatch.set_object_verifier(self.identity.verify_object)
        self.dispatch.set_cert_owner(self.db.identity.device_owner)
        self.station_set = StationObjectSet(self.dispatch, self.db.identity)
        self.mesh = MockMesh()
        self.keys: dict[str, Ed25519PrivateKey] = {}
        self.certs: dict[str, dict[str, Any]] = {}
        for node, user in PEOPLE.items():
            self.db.ensure_user(user, user.title())
            net = RNS.Identity()
            self.dispatch.bind_device(node, user, transport_dest=waylink_dest_hex(net.get_public_key())[0])
            sk = Ed25519PrivateKey.generate()
            self.keys[node] = sk
            self.certs[node] = self.identity.issue_device_cert(
                node_id=node, username=user,
                signing_key=sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), device_hash=net.hash)

    def verifier(self) -> OfflineVerifier:
        """What a device has cached from Station (D2)."""
        v = OfflineVerifier(self.key.public_bytes)
        for cert in self.certs.values():
            assert v.add_cert(cert)
        for rev in self.identity.revocations():
            v.add_cert(rev)
        return v

    def scout(self, node: str, *, interests: Optional[list[str]] = None, seed: int = 2) -> SyncNode:
        user = PEOPLE[node]
        return SyncNode(node_id=node, transport=self.mesh.attach(node, MockTransportConfig(1, 5, seed=seed)),
                        objects=MemoryObjectSet(self.verifier()), role="scout",
                        interests=interests or [f"u:{user}"], username=user,
                        signing_key=self.keys[node], cert_serial=self.certs[node]["n"])

    async def station(self) -> WaylinkGateway:
        gw = WaylinkGateway(self.mesh.attach("station", MockTransportConfig(1, 5, seed=1)), local_id="station")
        responder = SyncResponder(self.station_set, role="station", interests=lambda: ["*"])
        for op in (OP_HELLO, OP_SUM, OP_WANT, OP_PUT):
            gw.register(SVC_SYNC, op, responder.handle_rpc)
        await gw.start()
        return gw

    def station_bodies(self) -> list[str]:
        return sorted(r["body"] for r in self.db.dispatch._conn.execute("SELECT body FROM messages"))


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


def bodies(node: SyncNode) -> list[str]:
    return sorted(o["b"] for o in node.objects.objects.values())


async def test_two_scouts_without_station(world):
    """T1: Scout to Scout, nothing else on the air."""
    a, b = world.scout("pocket-1-aaaa"), world.scout("pocket-1-bbbb", seed=3)
    world.mesh.link(a.node_id, b.node_id)
    await a.start(), await b.start()
    try:
        a.write("water at the north tap", peer="basecamp")
        b.write("thanks, heading there", peer="ridgeline")
        r = await a.sync(b.node_id)
        assert r.ok and (r.pulled, r.pushed) == (1, 1)
        assert bodies(a) == bodies(b) == ["thanks, heading there", "water at the north tap"]
        again = await a.sync(b.node_id)
        assert (again.pulled, again.pushed) == (0, 0) and again.requests <= 3
    finally:
        await a.stop(), await b.stop()


async def test_station_reconciles_after_an_outage(world):
    """T2: what happened while Station was gone arrives in full, once."""
    a, b = world.scout("pocket-1-aaaa"), world.scout("pocket-1-bbbb", seed=3)
    world.mesh.link(a.node_id, b.node_id)
    await a.start(), await b.start()
    gw = await world.station()
    try:
        for i in range(3):
            a.write(f"ridgeline {i}", peer="basecamp")
            b.write(f"basecamp {i}", peer="ridgeline")
        await a.sync(b.node_id)
        world.mesh.link(a.node_id, "station")
        world.mesh.link(b.node_id, "station")
        ra = await a.sync("station")
        rb = await b.sync("station")
        assert ra.pushed == 6 and rb.pushed == 0 and not ra.rejected
        assert world.station_bodies() == sorted([f"ridgeline {i}" for i in range(3)] +
                                                [f"basecamp {i}" for i in range(3)])
        msgs = world.db.dispatch.list_messages("dm:basecamp:ridgeline")
        assert len(msgs) == 6 and all(m["sig"] for m in msgs)
        assert {m["sender"] for m in msgs} == {"ridgeline", "basecamp"}
    finally:
        await a.stop(), await b.stop(), await gw.stop()


async def test_courier_links_two_islands_then_station(world):
    """Scout -> courier -> Scout, and the courier's copy reaches Station later."""
    a = world.scout("pocket-1-aaaa")
    b = world.scout("pocket-1-bbbb", seed=3)
    courier = world.scout("pocket-1-cccc", interests=["u:carol", "u:basecamp"], seed=4)
    await a.start(), await b.start(), await courier.start()
    gw = await world.station()
    try:
        a.write("bring the spare antenna", peer="basecamp")
        world.mesh.link(courier.node_id, a.node_id)
        assert (await courier.sync(a.node_id)).pulled == 1
        world.mesh.link(courier.node_id, b.node_id)
        assert (await courier.sync(b.node_id)).pushed == 1
        assert bodies(b) == ["bring the spare antenna"]
        world.mesh.link(courier.node_id, "station")
        assert (await courier.sync("station")).pushed == 1
        (msg,) = world.db.dispatch.list_messages("dm:basecamp:ridgeline")
        assert msg["sender"] == "ridgeline"  # the author, not the courier
    finally:
        await a.stop(), await b.stop(), await courier.stop(), await gw.stop()


async def test_a_carrier_cannot_alter_or_forge(world):
    a, courier = world.scout("pocket-1-aaaa"), world.scout("pocket-1-cccc", interests=["u:carol", "u:basecamp"], seed=4)
    b = world.scout("pocket-1-bbbb", seed=3)
    await a.start(), await b.start(), await courier.start()
    try:
        a.write("meet at noon", peer="basecamp")
        world.mesh.link(courier.node_id, a.node_id)
        await courier.sync(a.node_id)
        (oid,) = courier.objects.objects
        courier.objects.objects[oid]["b"] = "meet at midnight"  # tampering in transit
        world.mesh.link(courier.node_id, b.node_id)
        r = await courier.sync(b.node_id)
        assert r.pushed == 0 and r.rejected == ["bad_signature"] and bodies(b) == []
    finally:
        await a.stop(), await b.stop(), await courier.stop()


async def test_revoked_device_is_refused_offline(world):
    a = world.scout("pocket-1-aaaa")
    world.dispatch.unbind_device("pocket-1-aaaa", username="ridgeline")  # lost Scout, revoked
    b = world.scout("pocket-1-bbbb", seed=3)  # synced revocations from Station (D2)
    world.mesh.link(a.node_id, b.node_id)
    await a.start(), await b.start()
    try:
        a.objects.verifier.revoked.clear()  # the lost Scout itself doesn't care
        a.write("from a revoked device", peer="basecamp")
        r = await a.sync(b.node_id)
        assert r.pushed == 0 and r.rejected == ["certificate_revoked"]
    finally:
        await a.stop(), await b.stop()


# -- efficiency and packet sizes (in process, every packet measured) -------------------


def _local_request(responder: SyncResponder, sizes: list[int]):
    async def request(op: str, payload: dict[str, Any]) -> Envelope:
        env = Envelope(src="outpost-00a1", dst="pocket-1-bbbb", svc=SVC_SYNC, op=op,
                       flags=int(Flags.REQUEST), payload=payload)
        sizes.append(len(encode_cbor(env)))
        reply = await responder.handle_rpc(env)
        sizes.append(len(encode_cbor(reply)))
        return reply
    return request


async def test_mostly_in_sync_costs_few_packets_and_every_packet_fits(world):
    writer = world.scout("pocket-1-aaaa")
    left = MemoryObjectSet(world.verifier())
    right = MemoryObjectSet(world.verifier())
    for i in range(300):
        obj = writer.write(f"shared message number {i} " + "x" * 90, peer="basecamp")
        left.put(obj), right.put(obj)
    only_left = [writer.write("left only " + "y" * 120, peer="basecamp") for _ in range(2)]
    only_right = [writer.write("right only", peer="basecamp") for _ in range(2)]
    for o in only_left:
        left.put(o)
    for o in only_right:
        right.put(o)
    sizes: list[int] = []
    responder = SyncResponder(right, role="outpost", interests=lambda: ["*"])
    r = await sync_with(_local_request(responder, sizes), left, role="outpost", interests=["*"])
    assert (r.pulled, r.pushed) == (2, 2) and not r.rejected
    assert sorted(left.objects) == sorted(right.objects)
    assert r.requests <= 15, r.requests  # 1 hello + a handful of SUMs + 2 WANT + 2 PUT
    assert max(sizes) <= RADIO_MDU, max(sizes)



async def test_a_message_at_the_compose_limit_travels_every_way(world):
    """The Scout limits typing to max_signed_body; such a message must make
    it Scout -> Scout -> Station, every packet one radio packet."""
    limit = max_signed_body("basecamp")
    assert 120 <= limit <= 140, limit
    writer = world.scout("pocket-1-aaaa")
    obj = writer.write("z" * limit, peer="basecamp")
    sizes: list[int] = []
    other = MemoryObjectSet(world.verifier())
    r = await sync_with(_local_request(SyncResponder(other, role="scout", interests=lambda: ["u:basecamp"]), sizes),
                        writer.objects, role="scout", interests=["u:ridgeline"])
    assert r.pushed == 1 and max(sizes) <= RADIO_MDU, max(sizes)
    sizes.clear()
    back = MemoryObjectSet(world.verifier())
    r = await sync_with(_local_request(SyncResponder(other, role="scout", interests=lambda: ["u:basecamp"]), sizes),
                        back, role="scout", interests=["u:ridgeline"])
    assert r.pulled == 1 and max(sizes) <= RADIO_MDU, max(sizes)
    assert max_signed_body("x" * 32) < limit and max_signed_body("room:" + "y" * 40, room=True) > 60
