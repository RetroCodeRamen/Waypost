"""Tests for RNS transport_dest binding (M2e)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from server.transports.reticulum import ReticulumTransport


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="test",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_bind_stores_transport_dest(client: TestClient):
    dest = "aabbccddeeff00112233445566778899"
    r = client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "rns-bob", "username": "bob", "transport_dest": dest},
    )
    assert r.status_code == 200
    assert r.json()["transport_dest"] == dest
    # persisted
    r2 = client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "rns-bob", "username": "bob"},
    )
    assert r2.json().get("transport_dest") == dest


def test_learn_route_resolves():
    t = ReticulumTransport(config_dir="/tmp/unused-rns-test", control_port=37999)
    t.learn_route("rns-bob", "aabbccddeeff00112233445566778899")
    assert t.resolve_destination("rns-bob") == "aabbccddeeff00112233445566778899"
    assert t.resolve_destination("other") == "other"


def test_learn_route_rejects_bad_hash():
    t = ReticulumTransport(config_dir="/tmp/unused-rns-test2", control_port=37998)
    with pytest.raises(ValueError):
        t.learn_route("rns-bob", "not-a-hash")
