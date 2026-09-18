"""API smoke tests."""

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
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "waypost-station"
    assert body["database"]["sqlite"] is True


def test_create_and_get_user(client: TestClient):
    r = client.post("/api/users", json={"username": "sarah", "display_name": "Sarah"})
    assert r.status_code == 201
    assert r.json()["username"] == "sarah"

    r2 = client.get("/api/users/sarah")
    assert r2.status_code == 200
    assert r2.json()["display_name"] == "Sarah"

    page = client.get("/~sarah")
    assert page.status_code == 200
    assert "Sarah" in page.text
    assert "Waypost" in page.text


def test_portal_index(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "Waypost" in r.text
