"""M4 — pairing codes and per-device revocation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.db import Database
from server.api.main import create_app
from server.services.auth.pairing import PairingService
from server.services.dispatch.service import DispatchService


# -- Service-level: precise control over code state (expiry, reuse) --


@pytest.fixture()
def pairing(tmp_path: Path) -> PairingService:
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch)
    return PairingService(db, dispatch)


def test_redeem_binds_device(pairing: PairingService):
    created = pairing.create_code("carol")
    assert len(created["code"]) == 6

    binding = pairing.redeem_code(code=created["code"], node_id="pocket-carol")
    assert binding["node_id"] == "pocket-carol"
    assert pairing.dispatch.store.get_binding("pocket-carol")["username"] == "carol"


def test_redeem_unknown_code_rejected(pairing: PairingService):
    with pytest.raises(ValueError, match="invalid"):
        pairing.redeem_code(code="000000", node_id="pocket-carol")


def test_redeem_expired_code_rejected(pairing: PairingService):
    pairing.db.create_pairing_code(
        code="123456", username="carol", created_at=0.0, expires_at=1.0
    )
    with pytest.raises(ValueError, match="expired"):
        pairing.redeem_code(code="123456", node_id="pocket-carol")


def test_redeem_used_code_rejected(pairing: PairingService):
    created = pairing.create_code("carol")
    pairing.redeem_code(code=created["code"], node_id="pocket-carol")
    with pytest.raises(ValueError, match="already used"):
        pairing.redeem_code(code=created["code"], node_id="pocket-carol-2")


# -- HTTP-level: end-to-end through the API, ownership checks --


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="development",
        waypost_auth_required=True,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, username: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert r.status_code == 200


def test_pairing_create_redeem_appears_in_device_list(client: TestClient):
    _register(client, "carol")
    code = client.post("/api/auth/pairing/create").json()["code"]

    redeemed = client.post(
        "/api/auth/pairing/redeem",
        json={"code": code, "node_id": "pocket-carol"},
    )
    assert redeemed.status_code == 200
    assert redeemed.json()["username"] == "carol"

    devices = client.get("/api/dispatch/devices").json()["devices"]
    assert any(d["node_id"] == "pocket-carol" for d in devices)


def test_redeem_does_not_require_a_session(client: TestClient):
    _register(client, "carol")
    code = client.post("/api/auth/pairing/create").json()["code"]
    client.cookies.clear()

    redeemed = client.post(
        "/api/auth/pairing/redeem",
        json={"code": code, "node_id": "pocket-carol"},
    )
    assert redeemed.status_code == 200


def test_unbind_one_only_removes_target(client: TestClient):
    _register(client, "carol")
    for node_id in ("pocket-carol", "radio-carol"):
        code = client.post("/api/auth/pairing/create").json()["code"]
        client.post(
            "/api/auth/pairing/redeem", json={"code": code, "node_id": node_id}
        )

    r = client.post(
        "/api/dispatch/devices/unbind-one",
        json={"node_id": "pocket-carol", "username": "carol"},
    )
    assert r.status_code == 200

    devices = client.get("/api/dispatch/devices").json()["devices"]
    node_ids = {d["node_id"] for d in devices}
    assert node_ids == {"radio-carol"}


def test_cannot_unbind_another_users_device(client: TestClient):
    _register(client, "carol")
    code = client.post("/api/auth/pairing/create").json()["code"]
    client.post("/api/auth/pairing/redeem", json={"code": code, "node_id": "pocket-carol"})

    _register(client, "dave")
    r = client.post(
        "/api/dispatch/devices/unbind-one",
        json={"node_id": "pocket-carol", "username": "dave"},
    )
    assert r.status_code == 404

    login = client.post(
        "/api/auth/login", json={"username": "carol", "password": "secret123"}
    )
    assert login.status_code == 200
    devices = client.get("/api/dispatch/devices").json()["devices"]
    assert any(d["node_id"] == "pocket-carol" for d in devices)


def test_devices_page_served(client: TestClient):
    r = client.get("/devices.html")
    assert r.status_code == 200
    assert "Devices" in r.text


def test_registration_mode_route(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="development",
        waypost_registration_mode="INVITE_ONLY",
    )
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/auth/registration_mode").json() == {"mode": "INVITE_ONLY"}
