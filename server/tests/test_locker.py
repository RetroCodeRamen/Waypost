"""Locker upload / download tests."""

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


def test_upload_list_download(client: TestClient):
    content = b"Trail map sketch - north ridge access.\n"
    r = client.post(
        "/api/locker/files",
        data={"owner": "bob", "scope": "shared", "note": "For everyone"},
        files={"file": ("trail-notes.txt", content, "text/plain")},
    )
    assert r.status_code == 201
    item = r.json()
    assert item["filename"] == "trail-notes.txt"
    assert item["scope"] == "shared"
    assert item["size"] == len(content)

    listed = client.get("/api/locker/files", params={"scope": "shared"})
    assert listed.status_code == 200
    assert any(f["id"] == item["id"] for f in listed.json()["files"])

    dl = client.get(f"/api/locker/files/{item['id']}/download")
    assert dl.status_code == 200
    assert dl.content == content
    assert "trail-notes.txt" in dl.headers.get("content-disposition", "")


def test_personal_hidden_from_others(client: TestClient):
    r = client.post(
        "/api/locker/files",
        data={"owner": "aj", "scope": "personal"},
        files={"file": ("private.txt", b"secret notes", "text/plain")},
    )
    assert r.status_code == 201
    fid = r.json()["id"]

    as_bob = client.get("/api/locker/files", params={"viewer": "bob"})
    assert all(f["id"] != fid for f in as_bob.json()["files"])

    as_aj = client.get(
        "/api/locker/files",
        params={"viewer": "aj", "scope": "personal", "owner": "aj"},
    )
    assert any(f["id"] == fid for f in as_aj.json()["files"])

    deny = client.get(f"/api/locker/files/{fid}/download", params={"viewer": "bob"})
    assert deny.status_code == 404

    ok = client.get(f"/api/locker/files/{fid}/download", params={"viewer": "aj"})
    assert ok.status_code == 200
    assert ok.content == b"secret notes"


def test_delete_owner_only(client: TestClient):
    r = client.post(
        "/api/locker/files",
        data={"owner": "aj", "scope": "shared"},
        files={"file": ("drop.txt", b"x", "text/plain")},
    )
    fid = r.json()["id"]
    forbidden = client.post(
        f"/api/locker/files/{fid}/delete",
        json={"actor": "bob"},
    )
    assert forbidden.status_code == 403

    deleted = client.post(
        f"/api/locker/files/{fid}/delete",
        json={"actor": "aj"},
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/locker/files/{fid}/download").status_code == 404


def test_locker_page(client: TestClient):
    r = client.get("/locker.html")
    assert r.status_code == 200
    assert "Locker" in r.text
    assert "locker.js" in r.text


def test_group_scoped_file_visible_only_to_members(client: TestClient):
    group = client.post("/api/groups", json={"name": "Trail Crew"}).json()
    gid = group["id"]
    client.post(f"/api/groups/{gid}/members", json={"username": "bob"})

    r = client.post(
        "/api/locker/files",
        data={"owner": "aj", "scope": "group", "group_id": gid},
        files={"file": ("crew-map.txt", b"crew only", "text/plain")},
    )
    assert r.status_code == 201
    fid = r.json()["id"]
    assert r.json()["group_id"] == gid

    as_member = client.get(
        "/api/locker/files", params={"viewer": "bob", "scope": "group", "group_id": gid}
    )
    assert any(f["id"] == fid for f in as_member.json()["files"])

    as_stranger = client.get(
        "/api/locker/files", params={"viewer": "carol", "scope": "group", "group_id": gid}
    )
    assert all(f["id"] != fid for f in as_stranger.json()["files"])

    deny = client.get(f"/api/locker/files/{fid}/download", params={"viewer": "carol"})
    assert deny.status_code == 404

    ok = client.get(f"/api/locker/files/{fid}/download", params={"viewer": "bob"})
    assert ok.status_code == 200


def test_group_scope_requires_membership_and_group_id(client: TestClient):
    missing_group = client.post(
        "/api/locker/files",
        data={"owner": "aj", "scope": "group"},
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert missing_group.status_code == 400

    group = client.post("/api/groups", json={"name": "Ops"}).json()
    not_a_member = client.post(
        "/api/locker/files",
        data={"owner": "carol", "scope": "group", "group_id": group["id"]},
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert not_a_member.status_code == 400


def test_empty_rejected(client: TestClient):
    r = client.post(
        "/api/locker/files",
        data={"owner": "aj", "scope": "shared"},
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert r.status_code == 400
