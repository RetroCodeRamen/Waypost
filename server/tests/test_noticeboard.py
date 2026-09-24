"""Noticeboard bulletin tests."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from server.services.noticeboard.service import NoticeboardService
from server.services.noticeboard.store import NoticeStore
from shared.protocol.envelope import SVC_NOTICEBOARD, Envelope, Flags


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


def test_ack_marks_notice_and_updates_unacked_count(client: TestClient):
    r = client.post(
        "/api/noticeboard/notices",
        json={"author": "bob", "title": "Trail closure", "body": "R2 closed."},
    )
    notice_id = r.json()["id"]

    before = client.get("/api/noticeboard/notices").json()
    assert before["unacked_count"] >= 1
    assert next(n for n in before["notices"] if n["id"] == notice_id)["acked"] is False

    ack = client.post(f"/api/noticeboard/notices/{notice_id}/ack", json={})
    assert ack.status_code == 200
    assert ack.json()["acked"] is True

    after = client.get("/api/noticeboard/notices").json()
    assert next(n for n in after["notices"] if n["id"] == notice_id)["acked"] is True

    # Idempotent — acking again doesn't error or double-count.
    ack2 = client.post(f"/api/noticeboard/notices/{notice_id}/ack", json={})
    assert ack2.status_code == 200
    assert after["unacked_count"] == client.get("/api/noticeboard/notices").json()["unacked_count"]


def test_ack_unknown_notice_404s(client: TestClient):
    r = client.post("/api/noticeboard/notices/does-not-exist/ack", json={})
    assert r.status_code == 404


# -- Radio-path authorization: NOTICE_CREATE/EXPIRE/ACK over Waylink must
# not trust a self-reported author/actor. Service-level with a stub
# binding lookup, same style as test_beacon.py.


def _memory_noticeboard_service(bindings: dict) -> NoticeboardService:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = NoticeStore(conn)
    return NoticeboardService(store, get_binding=lambda n: bindings.get(n))


def _env(src: str, op: str, payload: dict) -> Envelope:
    return Envelope(
        src=src,
        dst="station",
        svc=SVC_NOTICEBOARD,
        op=op,
        flags=int(Flags.REQUEST),
        payload=payload,
    )


def test_create_over_radio_rejects_unbound_device():
    from server.services.noticeboard.constants import OP_NOTICE_CREATE

    svc = _memory_noticeboard_service({})
    reply = svc.handle_rpc(
        _env("pocket-unknown", OP_NOTICE_CREATE, {"author": "aj", "title": "t", "body": "b"})
    )
    assert reply.payload["error"] == "unauthorized_device"
    assert svc.count_active() == 0


def test_create_over_radio_uses_bound_username_not_claimed_author():
    from server.services.noticeboard.constants import OP_NOTICE_CREATE

    svc = _memory_noticeboard_service({"pocket-carol": {"username": "carol"}})
    reply = svc.handle_rpc(
        _env(
            "pocket-carol",
            OP_NOTICE_CREATE,
            {"author": "aj", "title": "Water advisory", "body": "Boil water"},
        )
    )
    assert not (reply.flags & int(Flags.ERROR))
    assert reply.payload["notice"]["author"] == "carol"


def test_ack_over_radio_rejects_unbound_device():
    from server.services.noticeboard.constants import OP_NOTICE_ACK, OP_NOTICE_CREATE

    svc = _memory_noticeboard_service({"pocket-carol": {"username": "carol"}})
    created = svc.handle_rpc(
        _env("pocket-carol", OP_NOTICE_CREATE, {"title": "t", "body": "b"})
    )
    notice_id = created.payload["notice"]["id"]

    reply = svc.handle_rpc(_env("pocket-unknown", OP_NOTICE_ACK, {"id": notice_id}))
    assert reply.payload["error"] == "unauthorized_device"


def test_expire_over_radio_rejects_unbound_device():
    from server.services.noticeboard.constants import OP_NOTICE_CREATE, OP_NOTICE_EXPIRE

    svc = _memory_noticeboard_service({"pocket-carol": {"username": "carol"}})
    created = svc.handle_rpc(
        _env("pocket-carol", OP_NOTICE_CREATE, {"title": "t", "body": "b"})
    )
    notice_id = created.payload["notice"]["id"]

    reply = svc.handle_rpc(_env("pocket-unknown", OP_NOTICE_EXPIRE, {"id": notice_id}))
    assert reply.payload["error"] == "unauthorized_device"
    assert svc.count_active() == 1  # untouched


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
