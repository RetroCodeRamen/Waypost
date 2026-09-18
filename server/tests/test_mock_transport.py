"""Tests for MockTransport and envelope dedup/ping."""

from __future__ import annotations

import asyncio

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
async def test_cbor_roundtrip():
    env = Envelope(src="a", dst="b", svc="MAIL", op="MAIL_STATUS", payload={"x": True})
    raw = encode_cbor(env)
    back = decode_cbor(raw)
    assert back.svc == "MAIL"
    assert back.op == "MAIL_STATUS"
    assert back.payload == {"x": True}
    assert back.mid == env.mid
