"""M2e — ReticulumTransport start + announce (encrypted Waylink)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("RNS")

from server.transports.reticulum import ReticulumTransport


@pytest.mark.asyncio
async def test_reticulum_transport_starts_and_announces(tmp_path: Path):
    t = ReticulumTransport(
        config_dir=tmp_path / "rns",
        control_port=37701,
        node_id="station-test",
    )
    await t.start()
    try:
        assert t.destination_hash_hex
        assert len(t.destination_hash_hex) == 32
        assert (tmp_path / "rns" / "identity").exists()
        assert (tmp_path / "rns" / "config").exists()
    finally:
        await t.stop()


@pytest.mark.asyncio
async def test_send_outpost_claim_ack_targets_announced_hash(tmp_path: Path):
    t = ReticulumTransport(
        config_dir=tmp_path / "rns-ack",
        control_port=37702,
        node_id="station-test",
    )
    captured: list = []

    async def _capture_send(packet):
        captured.append(packet)

    t.send = _capture_send  # type: ignore[method-assign]
    dest = "aa" * 16
    await t.send_outpost_claim_ack("outpost-1-0e21", dest)
    assert len(captured) == 1
    assert captured[0].destination == dest
    payload = captured[0].payload
    assert b"claimed" in payload
    assert b"outpost-1-0e21" in payload
