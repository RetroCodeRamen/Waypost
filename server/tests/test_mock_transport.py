"""Tests for MockTransport and envelope dedup/ping."""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from server.gateway.waylink import WaylinkGateway
from server.transports.base import TransportPacket
from server.transports.mock import MockMesh, MockTransportConfig
from shared.protocol.envelope import (
    OP_PONG,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
    new_id,
)


@pytest.mark.asyncio
async def test_mock_send_receive():
    mesh = MockMesh()
    a = mesh.attach("pocket-a", MockTransportConfig(latency_ms_min=1, latency_ms_max=5, seed=1))
    b = mesh.attach("pocket-b", MockTransportConfig(latency_ms_min=1, latency_ms_max=5, seed=2))
    await a.start()
    await b.start()

    await a.send(
        TransportPacket(
            destination="pocket-b",
            payload=b"hello",
            source="pocket-a",
            message_id=new_id(),
        )
    )
    got = await b.receive_one(timeout=2)
    assert got.payload == b"hello"
    assert got.source == "pocket-a"

    await a.stop()
    await b.stop()


@pytest.mark.asyncio
async def test_mock_unreachable_when_disconnected():
    mesh = MockMesh()
    a = mesh.attach("a")
    b = mesh.attach("b", connected=False)
    await a.start()
    await b.start()
    assert await a.reachable("b") is False
    await a.stop()
    await b.stop()


@pytest.mark.asyncio
async def test_mock_dedup_on_duplicate_delivery():
    mesh = MockMesh()
    cfg = MockTransportConfig(
        latency_ms_min=1,
        latency_ms_max=2,
        duplicate_rate=1.0,
        seed=42,
    )
    a = mesh.attach("a", cfg)
    b = mesh.attach("b", MockTransportConfig(latency_ms_min=1, latency_ms_max=2, seed=7))
    await a.start()
    await b.start()

    mid = new_id()
    await a.send(
        TransportPacket(destination="b", payload=b"x", source="a", message_id=mid)
    )
    first = await b.receive_one(timeout=2)
    # Second enqueue suppressed by message_id dedup on receiver
    with pytest.raises(asyncio.TimeoutError):
        await b.receive_one(timeout=0.3)
    assert first.message_id == mid

    await a.stop()
    await b.stop()


@pytest.mark.asyncio
async def test_gateway_ping_pong():
    mesh = MockMesh()
    station_t = mesh.attach(
        "station",
        MockTransportConfig(latency_ms_min=1, latency_ms_max=3, seed=1),
    )
    pocket_t = mesh.attach(
        "pocket",
        MockTransportConfig(latency_ms_min=1, latency_ms_max=3, seed=2),
    )

    gateway = WaylinkGateway(station_t, local_id="station")
    await gateway.start()
    await pocket_t.start()

    env = Envelope(
        src="pocket",
        dst="station",
        svc="CORE",
        op="PING",
        flags=int(Flags.REQUEST),
        payload={"n": 1},
    )
    await pocket_t.send(
        TransportPacket(
            destination="station",
            payload=encode_cbor(env),
            source="pocket",
            message_id=env.mid,
        )
    )

    reply_packet = await pocket_t.receive_one(timeout=2)
    reply = decode_cbor(reply_packet.payload)
    assert reply.op == OP_PONG
    assert reply.rid == env.rid
    assert reply.payload == {"echo": {"n": 1}}

    await gateway.stop()
    await pocket_t.stop()


@pytest.mark.asyncio
async def test_gateway_survives_a_handler_exception():
    """Regression: WaylinkGateway._loop() ran as a fire-and-forget
    asyncio.Task with no exception handling anywhere in its chain -- a
    single unhandled exception while decoding, handling, or replying to
    one packet silently killed the entire receive loop forever, with no
    log line ever surfacing it (asyncio only warns on an unretrieved
    task's exception when that Task is garbage-collected, and the
    gateway holds its own task reference for the app's whole lifetime,
    so it never was). This is the real root cause behind "it worked
    once, then never again" seen repeatedly on real hardware (Outpost
    BOARD_SYNC, Scout CORE/PING) -- not a radio/transmit bug."""
    mesh = MockMesh()
    station_t = mesh.attach(
        "station2", MockTransportConfig(latency_ms_min=1, latency_ms_max=3, seed=3)
    )
    pocket_t = mesh.attach(
        "pocket2", MockTransportConfig(latency_ms_min=1, latency_ms_max=3, seed=4)
    )

    gateway = WaylinkGateway(station_t, local_id="station2")
    gateway.register(
        "BOOM", "FAIL", lambda env: (_ for _ in ()).throw(RuntimeError("handler blew up"))
    )
    await gateway.start()
    await pocket_t.start()

    async def send_and_get_reply(svc: str, op: str, payload: dict) -> Optional[Envelope]:
        env = Envelope(
            src="pocket2",
            dst="station2",
            svc=svc,
            op=op,
            flags=int(Flags.REQUEST),
            payload=payload,
        )
        await pocket_t.send(
            TransportPacket(
                destination="station2",
                payload=encode_cbor(env),
                source="pocket2",
                message_id=env.mid,
            )
        )
        try:
            reply_packet = await pocket_t.receive_one(timeout=1)
        except asyncio.TimeoutError:
            return None
        return decode_cbor(reply_packet.payload)

    # First packet's handler raises -- must not take down the loop.
    assert await send_and_get_reply("BOOM", "FAIL", {}) is None

    # The loop must still be alive and answer a completely unrelated,
    # well-behaved request afterward.
    reply = await send_and_get_reply("CORE", "PING", {"n": 2})
    assert reply is not None
    assert reply.op == OP_PONG
    assert reply.payload == {"echo": {"n": 2}}

    await gateway.stop()
    await pocket_t.stop()


@pytest.mark.asyncio
async def test_cbor_roundtrip():
    env = Envelope(src="a", dst="b", svc="MAIL", op="MAIL_STATUS", payload={"x": True})
    raw = encode_cbor(env)
    back = decode_cbor(raw)
    assert back.svc == "MAIL"
    assert back.op == "MAIL_STATUS"
    assert back.payload == {"x": True}
    assert back.mid == env.mid


def test_mock_transport_exposes_full_transport_interface():
    """Regression: learn_route/resolve_destination/destination_hash_hex/
    on_unclaimed_outpost_announce used to exist only on ReticulumTransport,
    guarded everywhere with hasattr() -- meaning a broken wire-up silently
    no-op'd under the entire test suite (MockTransport) instead of failing.
    Now every Transport (base.py) declares them with sane no-op defaults."""
    mesh = MockMesh()
    t = mesh.attach("pocket-iface-check")

    assert t.on_unclaimed_outpost_announce is None
    t.on_unclaimed_outpost_announce = lambda node_id, dest, name: None
    assert callable(t.on_unclaimed_outpost_announce)

    # No-op: doesn't raise, doesn't need a real transport_dest format.
    t.learn_route("pocket-b", "not-a-real-hash")

    # Identity: no routing layer of its own to resolve through.
    assert t.resolve_destination("pocket-b") == "pocket-b"

    assert t.destination_hash_hex is None
