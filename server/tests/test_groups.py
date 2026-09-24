"""Groups core tests."""

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


def test_create_group_makes_creator_admin(client: TestClient):
    r = client.post("/api/groups", json={"name": "Trail Crew"})
    assert r.status_code == 201
    group = r.json()
    assert group["name"] == "Trail Crew"
    assert len(group["members"]) == 1
    assert group["members"][0]["username"] == "aj"
    assert group["members"][0]["role"] == "admin"


def test_list_groups_scoped_to_membership(client: TestClient):
    created = client.post(
        "/api/groups", json={"name": "Family"}
    ).json()

    # aj (the caller in test mode) is a member/admin, sees it in their list.
    mine = client.get("/api/groups").json()["groups"]
    assert any(g["id"] == created["id"] for g in mine)


def test_admin_can_add_and_remove_member(client: TestClient):
    group = client.post("/api/groups", json={"name": "Maintenance"}).json()
    gid = group["id"]

    added = client.post(
        f"/api/groups/{gid}/members", json={"username": "bob", "role": "member"}
    )
    assert added.status_code == 200
    usernames = {m["username"] for m in added.json()["members"]}
    assert "bob" in usernames

    removed = client.post(
        f"/api/groups/{gid}/members/remove", json={"username": "bob"}
    )
    assert removed.status_code == 200
    usernames = {m["username"] for m in removed.json()["members"]}
    assert "bob" not in usernames


def test_non_admin_cannot_add_member(client: TestClient):
    group = client.post("/api/groups", json={"name": "Ops"}).json()
    gid = group["id"]
    client.post(f"/api/groups/{gid}/members", json={"username": "bob", "role": "member"})

    # bob is a plain member, not admin — attempting to add someone else
    # should be rejected. Test-mode auth always resolves the caller as
    # "aj" (the seeded admin), so exercise the service layer directly to
    # simulate a non-admin actor.
    from server.services.groups.service import GroupsService

    svc: GroupsService = client.app.state.groups
    with pytest.raises(PermissionError):
        svc.add_member(gid, actor="bob", username="carol")


def test_cannot_remove_last_admin(client: TestClient):
    group = client.post("/api/groups", json={"name": "Solo"}).json()
    gid = group["id"]
    svc = client.app.state.groups
    with pytest.raises(ValueError):
        svc.remove_member(gid, actor="aj", username="aj")


def test_get_unknown_group_404s(client: TestClient):
    r = client.get("/api/groups/does-not-exist")
    assert r.status_code == 404


def _session_headers(client: TestClient, username: str) -> dict[str, str]:
    """Real Bearer session for a second identity; honored even in test env."""
    client.app.state.db.ensure_user(username)
    token = client.app.state.auth.create_session(username)["token"]
    return {"Authorization": f"Bearer {token}"}


def test_non_member_cannot_read_group_or_roster(client: TestClient):
    gid = client.post("/api/groups", json={"name": "Private"}).json()["id"]
    bob = _session_headers(client, "bob")

    # Indistinguishable from a missing group — no existence oracle.
    assert client.get(f"/api/groups/{gid}", headers=bob).status_code == 404
    assert client.get(f"/api/groups/{gid}/members", headers=bob).status_code == 404
    assert client.get("/api/groups", headers=bob).json()["groups"] == []

    # Members still see it.
    assert client.get(f"/api/groups/{gid}").status_code == 200
    assert client.get(f"/api/groups/{gid}/members").status_code == 200


def test_non_member_cannot_seed_room_from_group(client: TestClient):
    gid = client.post("/api/groups", json={"name": "Crew"}).json()["id"]
    client.post(f"/api/groups/{gid}/members", json={"username": "carol"})
    bob = _session_headers(client, "bob")

    denied = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "Sneaky", "group_id": gid},
        headers=bob,
    )
    assert denied.status_code == 403

    missing = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "Nope", "group_id": "does-not-exist"},
        headers=bob,
    )
    assert missing.status_code == 404

    # A member can still seed a room from the group's roster.
    ok = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "Crew chat", "group_id": gid},
    )
    assert ok.status_code == 200
    assert set(ok.json()["conversation"]["members"]) == {"aj", "carol"}


def test_cannot_demote_last_admin_via_add(client: TestClient):
    gid = client.post("/api/groups", json={"name": "Solo"}).json()["id"]

    r = client.post(f"/api/groups/{gid}/members", json={"username": "aj", "role": "member"})
    assert r.status_code == 400
    assert "last admin" in r.json()["detail"]
    assert client.get(f"/api/groups/{gid}").json()["members"][0]["role"] == "admin"

    # Promote someone else first, then the demotion is allowed.
    client.post(f"/api/groups/{gid}/members", json={"username": "bob", "role": "admin"})
    r = client.post(f"/api/groups/{gid}/members", json={"username": "aj", "role": "member"})
    assert r.status_code == 200
    roles = {m["username"]: m["role"] for m in r.json()["members"]}
    assert roles == {"aj": "member", "bob": "admin"}


def test_groups_page(client: TestClient):
    r = client.get("/groups.html")
    assert r.status_code == 200
    assert "Groups" in r.text
    assert "groups.js" in r.text
