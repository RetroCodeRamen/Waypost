"""Beacon emergency alert tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="test",
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_push_get_clear(client: TestClient):
    r = client.post(
        "/api/beacon",
        json={
            "author": "aj",
            "title": "Fire near north ridge",
            "body": "Stay clear of trail R1. Muster at commons hall.",
            "severity": "emergency",
        },
    )
    assert r.status_code == 201
    beacon = r.json()
    assert beacon["active"] is True

    active = client.get("/api/beacon")
    assert active.status_code == 200
    assert active.json()["beacon"]["id"] == beacon["id"]

    # Second push replaces active
    r2 = client.post(
        "/api/beacon",
        json={
            "author": "bob",
            "title": "All clear pending",
            "body": "Staging only.",
            "severity": "urgent",
        },
    )
    assert r2.status_code == 201
    assert client.get("/api/beacon").json()["beacon"]["id"] == r2.json()["id"]

    cleared = client.post("/api/beacon/clear", json={})
    assert cleared.status_code == 200
    assert client.get("/api/beacon").json()["beacon"] is None


def test_mid_replay_idempotent(client: TestClient):
    payload = {
        "author": "aj",
        "title": "Replay check",
        "body": "Same mid should not duplicate.",
        "mid": "fixed-mid-beacon-1",
    }
    a = client.post("/api/beacon", json=payload)
    b = client.post("/api/beacon", json=payload)
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    hist = client.get("/api/beacon/history").json()["beacons"]
    assert sum(1 for x in hist if x.get("mid") == "fixed-mid-beacon-1") == 1


def test_beacon_page(client: TestClient):
    r = client.get("/beacon.html")
    assert r.status_code == 200
    assert "Beacon" in r.text


def test_dashboard_beacon(client: TestClient):
    client.post(
        "/api/beacon",
        json={
            "author": "bob",
            "title": "Medical standby",
            "body": "Need first-aid kit at Outpost 02.",
            "severity": "urgent",
        },
    )
    r = client.get("/api/dashboard", params={"username": "aj"})
    assert r.status_code == 200
    body = r.json()
    assert body["active_beacon"]["title"] == "Medical standby"
    assert any(a["service"] == "Beacon" for a in body["activity"])
