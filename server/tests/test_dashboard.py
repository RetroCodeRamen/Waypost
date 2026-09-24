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


def test_noticeboard_card_is_unread_for_caller_not_global_active_count(
    client: TestClient,
):
    a = client.post(
        "/api/noticeboard/notices",
        json={"author": "bob", "title": "Trail closure", "body": "R2 closed"},
    ).json()
    client.post(
        "/api/noticeboard/notices",
        json={"author": "bob", "title": "Water advisory", "body": "Boil water"},
    )

    before = client.get("/api/dashboard", params={"username": "aj"}).json()
    assert before["cards"]["noticeboard"]["value"] == 2
    assert before["cards"]["noticeboard"]["label"] == "Unread Notices"

    client.post(f"/api/noticeboard/notices/{a['id']}/ack", json={"username": "aj"})

    after = client.get("/api/dashboard", params={"username": "aj"}).json()
    assert after["cards"]["noticeboard"]["value"] == 1  # one acked, one still unread

    # A different user's ack state is independent.
    carol_view = client.get("/api/dashboard", params={"username": "carol"}).json()
    assert carol_view["cards"]["noticeboard"]["value"] == 2


def test_sync_aggregate_includes_postbox_outbox(client: TestClient):
    baseline = client.get("/api/dashboard", params={"username": "aj"}).json()
    assert baseline["sync"]["pending_total"] == 0

    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Hold this",
            "body": "Not sent yet.",
            "queue_only": True,
        },
    )

    after = client.get("/api/dashboard", params={"username": "aj"}).json()
    assert after["sync"]["pending_mail_outbox"] == 1
    assert after["sync"]["pending_total"] == 1


def test_home_page_has_shell_hooks(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "wp-page" in r.text
    assert "tokens.css" in r.text
    assert "shell.js" in r.text
    assert "Recent Activity" in r.text
