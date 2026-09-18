"""Rollcall presence tests."""

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


def test_rollcall_lists_people_with_reachability(client: TestClient):
    client.post(
        "/api/rollcall/status",
        json={"username": "aj", "status": "Working on north outpost"},
    )
    client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    people = client.get("/api/rollcall").json()["people"]
    by_name = {p["username"].lower(): p for p in people}
    assert "aj" in by_name
    assert by_name["aj"]["status"] == "Working on north outpost"
    assert "wifi" in by_name["aj"]["reachability"]
    assert "lora" in by_name["bob"]["reachability"]


def test_rollcall_page(client: TestClient):
    assert client.get("/rollcall.html").status_code == 200
