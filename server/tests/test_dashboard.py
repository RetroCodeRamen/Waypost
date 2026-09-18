"""Dashboard aggregate tests."""

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


def test_dashboard_payload(client: TestClient):
    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "bob",
            "to": "aj@waypost",
            "subject": "Hello",
            "body": "From the trail",
        },
    )
    r = client.get("/api/dashboard", params={"username": "aj"})
    assert r.status_code == 200
    body = r.json()
    assert body["cards"]["postbox"]["value"] >= 1
    assert body["network"]["station"] == "Online"
    assert any(a["service"] == "Postbox" for a in body["activity"])


def test_home_page_has_shell_hooks(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "wp-page" in r.text
    assert "tokens.css" in r.text
    assert "shell.js" in r.text
    assert "Recent Activity" in r.text
