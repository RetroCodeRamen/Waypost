"""Signal diagnostics tests."""

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


def test_signal_status(client: TestClient):
    r = client.get("/api/signal")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["waylink"]["transport"] == "mock"
    assert body["services"]["beacon"] is True
    assert "station" in body


def test_signal_route_probe(client: TestClient):
    r = client.get("/api/signal/route", params={"destination": "pocket-bob"})
    assert r.status_code == 200
    body = r.json()
    assert body["destination"] == "pocket-bob"
    assert "reachable" in body


def test_signal_page(client: TestClient):
    r = client.get("/signal.html")
    assert r.status_code == 200
    assert "Signal" in r.text
    assert "signal.js" in r.text


def test_health_reports_signal(client: TestClient):
    r = client.get("/api/health")
    assert r.json()["signal"] is True
    assert r.json()["beacon"] is True


def test_signal_lists_radios_field(client: TestClient):
    r = client.get("/api/signal")
    body = r.json()
    assert "radios" in body["waylink"]
    assert "radios_detected" in body["waylink"]
