"""N2 account auth tests."""

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
        waypost_env="development",  # auth required
        waypost_auth_required=True,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_register_login_me(client: TestClient):
    r = client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "secret123", "display_name": "Carol"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "carol"
    assert "token" in r.json()
    token = r.json()["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "carol"

    bad = client.post(
        "/api/auth/login", json={"username": "carol", "password": "wrongpass"}
    )
    assert bad.status_code == 401

    ok = client.post(
        "/api/auth/login", json={"username": "carol", "password": "secret123"}
    )
    assert ok.status_code == 200


def test_send_requires_auth_and_uses_session_user(client: TestClient):
    client.post(
        "/api/auth/register",
        json={"username": "dave", "password": "secret123"},
    )
    # Register sets cookie on TestClient
    sent = client.post(
        "/api/dispatch/messages",
        json={"sender": "someone-else", "peer": "aj", "body": "Hi from dave"},
    )
    assert sent.status_code == 200
    assert sent.json()["message"]["sender"] == "dave"


def test_login_page_served(client: TestClient):
    r = client.get("/login.html")
    assert r.status_code == 200
    assert "Sign in" in r.text


def test_private_apis_require_auth(client: TestClient):
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/commons/posts").status_code == 401
    assert client.get("/api/postbox/status?mailbox=aj").status_code == 401
    assert client.get("/api/signal").status_code == 401
    # health stays public
    assert client.get("/api/health").status_code == 200


def test_cannot_spoof_sender(client: TestClient):
    client.post(
        "/api/auth/register",
        json={"username": "erin", "password": "secret123"},
    )
    sent = client.post(
        "/api/commons/posts",
        json={"author": "aj", "body": "spoof attempt"},
    )
    assert sent.status_code == 201
    assert sent.json()["author"] == "erin"
