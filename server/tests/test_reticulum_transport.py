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
