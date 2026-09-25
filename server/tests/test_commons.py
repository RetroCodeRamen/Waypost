"""Commons feed tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from shared.protocol.envelope import SVC_COMMONS, Envelope, Flags
from server.services.commons.constants import OP_POST_CREATE, OP_POST_LIST


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


def test_create_and_list_posts(client: TestClient):
    r = client.post(
        "/api/commons/posts",
        json={
            "author": "bob",
            "title": "Trail day",
            "body": "Clearing brush near Outpost 02 this Saturday.",
        },
    )
    assert r.status_code == 201
    post = r.json()
    assert post["author"] == "bob"
    assert post["title"] == "Trail day"
    assert "id" in post

    listed = client.get("/api/commons/posts")
    assert listed.status_code == 200
    posts = listed.json()["posts"]
    assert any(p["id"] == post["id"] for p in posts)

    got = client.get(f"/api/commons/posts/{post['id']}")
    assert got.status_code == 200
    assert got.json()["body"].startswith("Clearing")


def test_empty_body_rejected(client: TestClient):
    r = client.post(
        "/api/commons/posts",
        json={"author": "aj", "body": "   "},
    )
    assert r.status_code == 400


def test_commons_page(client: TestClient):
    r = client.get("/commons.html")
    assert r.status_code == 200
    assert "Commons" in r.text
    assert "commons.js" in r.text
    # Identity comes from a real session, not a free-text box (M9 fix).
    assert "auth.js" in r.text
    assert 'id="me"' not in r.text


def test_group_scoped_post_visible_only_to_members(client: TestClient):
    group = client.post("/api/groups", json={"name": "Trail Crew"}).json()
    gid = group["id"]
    client.post(f"/api/groups/{gid}/members", json={"username": "bob"})

    r = client.post(
        "/api/commons/posts",
        json={
            "author": "aj",
            "title": "Crew update",
            "body": "Brush clearing Saturday.",
            "group_id": gid,
        },
    )
    assert r.status_code == 201
    post_id = r.json()["id"]
    assert r.json()["group_id"] == gid

    as_member = client.get("/api/commons/posts", params={"viewer": "bob"})
    assert any(p["id"] == post_id for p in as_member.json()["posts"])

    as_stranger = client.get("/api/commons/posts", params={"viewer": "carol"})
    assert all(p["id"] != post_id for p in as_stranger.json()["posts"])

    deny = client.get(f"/api/commons/posts/{post_id}", params={"viewer": "carol"})
    assert deny.status_code == 404


def test_group_post_requires_membership_to_create(client: TestClient):
    group = client.post("/api/groups", json={"name": "Ops"}).json()
    r = client.post(
        "/api/commons/posts",
        json={
            "author": "carol",
            "body": "Should fail.",
            "group_id": group["id"],
        },
    )
    assert r.status_code == 400


def test_store_search_ranks_title_hits_first(client: TestClient):
    client.post(
        "/api/commons/posts",
        json={"author": "aj", "title": "Unrelated", "body": "mentions lantern once"},
    )
    client.post(
        "/api/commons/posts",
        json={"author": "aj", "title": "Lantern repair", "body": "fixed the shed light"},
    )
    hits = client.app.state.db.commons.search("lantern")
    assert len(hits) == 2
    assert hits[0]["title"] == "Lantern repair"
    assert hits[0]["title_hit"] > 0

    assert client.app.state.db.commons.search("") == []
    assert client.app.state.db.commons.search("no-such-term-anywhere") == []


def test_dashboard_includes_commons(client: TestClient):
    client.post(
        "/api/commons/posts",
        json={"author": "bob", "body": "Generator fuel is in the shed."},
    )
    r = client.get("/api/dashboard", params={"username": "aj"})
    assert r.status_code == 200
    body = r.json()
    assert body["cards"]["commons"]["value"] >= 1
    assert "soon" not in body["cards"]["commons"]
    assert any(a["service"] == "Commons" for a in body["activity"])
    assert any(l["href"] == "/commons.html" for l in body["quick_links"])


def test_health_reports_commons(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["commons"] is True


def test_commons_rpc_via_gateway(client: TestClient):
    app = client.app
    gateway = app.state.gateway
    env = Envelope(
        src="pocket-bob",
        dst="station",
        svc=SVC_COMMONS,
        op=OP_POST_CREATE,
        flags=int(Flags.REQUEST),
        payload={"author": "bob", "body": "LoRa-side note from the ridge."},
    )
    # Direct handler path used by Waylink gateway
    resp = app.state.commons.handle_rpc(env)
    assert not (resp.flags & int(Flags.ERROR))
    assert resp.payload["post"]["body"].startswith("LoRa-side")

    listed = app.state.commons.handle_rpc(
        Envelope(
            src="pocket-aj",
            dst="station",
            svc=SVC_COMMONS,
            op=OP_POST_LIST,
            flags=int(Flags.REQUEST),
            payload={"limit": 10},
        )
    )
    assert any(
        p["body"].startswith("LoRa-side") for p in listed.payload["posts"]
    )
    assert gateway is not None
