"""Noticeboard bulletin tests."""

from __future__ import annotations

import time
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


def test_create_list_expire(client: TestClient):
    r = client.post(
        "/api/noticeboard/notices",
        json={
            "author": "aj",
            "title": "Well maintenance Tuesday",
            "body": "Pump house closed 09:00–12:00.",
            "priority": "high",
        },
    )
    assert r.status_code == 201
    notice = r.json()
    assert notice["priority"] == "high"
    assert notice["active"] is True

    listed = client.get("/api/noticeboard/notices")
    assert listed.status_code == 200
    body = listed.json()
    assert body["active_count"] >= 1
    assert any(n["id"] == notice["id"] for n in body["notices"])

    expired = client.post(f"/api/noticeboard/notices/{notice['id']}/expire")
    assert expired.status_code == 200
    assert expired.json()["active"] is False

    listed2 = client.get("/api/noticeboard/notices")
    assert all(n["id"] != notice["id"] for n in listed2.json()["notices"])


def test_auto_expire(client: TestClient):
    past = time.time() - 10
    r = client.post(
        "/api/noticeboard/notices",
        json={
            "author": "bob",
            "title": "Expired already",
            "body": "Should drop out of active list.",
            "expires_at": past,
        },
    )
    assert r.status_code == 201
    listed = client.get("/api/noticeboard/notices", params={"active_only": True})
    assert all(n["title"] != "Expired already" for n in listed.json()["notices"])


def test_noticeboard_page(client: TestClient):
    r = client.get("/noticeboard.html")
    assert r.status_code == 200
    assert "Noticeboard" in r.text


def test_dashboard_noticeboard(client: TestClient):
    client.post(
        "/api/noticeboard/notices",
        json={
            "author": "bob",
            "title": "Water advisory",
            "body": "Boil water until further notice.",
            "priority": "high",
        },
    )
    r = client.get("/api/dashboard", params={"username": "aj"})
    assert r.status_code == 200
    body = r.json()
    assert body["cards"]["noticeboard"]["value"] >= 1
    assert "soon" not in body["cards"]["noticeboard"]
    assert any(a["service"] == "Noticeboard" for a in body["activity"])
