"""Finder — cross-app search, respecting every service's own privacy rules."""

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


def _session_headers(client: TestClient, username: str) -> dict[str, str]:
    """Real Bearer session for a second identity; honored even in test env
    (unlike a claimed `viewer=` query param on a route with no session,
    which in this test env just resolves to whatever "aj" already is)."""
    client.app.state.db.ensure_user(username)
    token = client.app.state.auth.create_session(username)["token"]
    return {"Authorization": f"Bearer {token}"}


def test_search_finds_commons_and_fieldbook(client: TestClient):
    client.post(
        "/api/commons/posts",
        json={"author": "aj", "title": "Trail cleanup", "body": "Saturday at the ridge trailhead"},
    )
    client.post(
        "/api/fieldbook/pages",
        json={"title": "Ridge Trailhead", "body": "Parking and directions to the ridge trailhead."},
    )

    r = client.get("/api/finder/search", params={"q": "ridge trailhead"})
    assert r.status_code == 200
    services = {item["service"] for item in r.json()["results"]}
    assert "commons" in services
    assert "fieldbook" in services


def test_empty_query_returns_nothing(client: TestClient):
    r = client.get("/api/finder/search", params={"q": ""})
    assert r.json()["results"] == []


def test_title_hits_rank_before_body_hits(client: TestClient):
    client.post(
        "/api/commons/posts",
        json={"author": "aj", "title": "Unrelated", "body": "mentions zephyr only in passing"},
    )
    client.post(
        "/api/commons/posts",
        json={"author": "aj", "title": "Zephyr radio check", "body": "weekly check-in"},
    )
    r = client.get("/api/finder/search", params={"q": "zephyr"})
    results = [x for x in r.json()["results"] if x["service"] == "commons"]
    assert len(results) == 2
    assert results[0]["title"] == "Zephyr radio check"


def test_group_scoped_notice_hidden_from_non_member(client: TestClient):
    gid = client.post("/api/groups", json={"name": "Crew Only"}).json()["id"]
    client.post(f"/api/groups/{gid}/members", json={"username": "bob"})
    client.post(
        "/api/noticeboard/notices",
        json={
            "author": "aj",
            "title": "Crew rendezvous point",
            "body": "Meet at the old fire tower",
            "group_id": gid,
        },
    )

    # aj (admin/member of the group, via the default test-mode identity)
    as_member = client.get("/api/finder/search", params={"q": "rendezvous"})
    assert any(r["service"] == "noticeboard" for r in as_member.json()["results"])

    # A real non-member session must not see it.
    carol = _session_headers(client, "carol")
    as_stranger = client.get(
        "/api/finder/search", params={"q": "rendezvous"}, headers=carol
    )
    assert not any(r["service"] == "noticeboard" for r in as_stranger.json()["results"])


def test_personal_locker_file_hidden_from_others(client: TestClient):
    client.post(
        "/api/locker/files",
        data={"owner": "aj", "scope": "personal", "note": "confidential trip notes"},
        files={"file": ("private-notes.txt", b"secret", "text/plain")},
    )

    as_owner = client.get("/api/finder/search", params={"q": "confidential"})
    assert any(r["service"] == "locker" for r in as_owner.json()["results"])

    bob = _session_headers(client, "bob")
    as_bob = client.get(
        "/api/finder/search", params={"q": "confidential"}, headers=bob
    )
    assert not any(r["service"] == "locker" for r in as_bob.json()["results"])


def test_finder_page_served(client: TestClient):
    r = client.get("/finder.html")
    assert r.status_code == 200
    assert "Finder" in r.text
    assert "finder.js" in r.text
