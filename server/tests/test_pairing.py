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
from shared.protocol.envelope import OP_OUTPOST_CLAIM, SVC_CORKBOARD, Envelope, Flags


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


# -- Outpost claiming: same codes, different redemption target --


class _StubTransport:
    """Just enough of the Transport interface to prove redeem_outpost_code
    calls learn_route with the right args before it returns — the actual
    "reply now routes correctly" timing is WaylinkGateway's job (handler
    runs to completion, then send_envelope resolves the destination), not
    something a stub here can usefully re-prove."""

    def __init__(self) -> None:
        self.routes: dict[str, str] = {}

    def learn_route(self, node_id: str, transport_dest: str) -> None:
        self.routes[node_id] = transport_dest


@pytest.fixture()
def pairing_with_corkboard(tmp_path: Path) -> PairingService:
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch)
    svc = PairingService(db, dispatch, corkboard_store=db.corkboard)
    svc.transport = _StubTransport()
    return svc


def test_claim_outpost_registers_and_learns_route(pairing_with_corkboard: PairingService):
    created = pairing_with_corkboard.create_code("aj")
    result = pairing_with_corkboard.redeem_outpost_code(
        code=created["code"],
        node_id="outpost-1",
        transport_dest="aa" * 16,
        display_name="Ridge Trailhead",
    )
    assert result["node_id"] == "outpost-1"
    assert result["outpost"]["display_name"] == "Ridge Trailhead"
    assert result["outpost"]["transport_dest"] == "aa" * 16
    assert pairing_with_corkboard.transport.routes["outpost-1"] == "aa" * 16
    assert pairing_with_corkboard.corkboard_store.get_outpost("outpost-1") is not None


def test_claim_outpost_rejects_bad_transport_dest(pairing_with_corkboard: PairingService):
    created = pairing_with_corkboard.create_code("aj")
    with pytest.raises(ValueError, match="32 hex"):
        pairing_with_corkboard.redeem_outpost_code(
            code=created["code"], node_id="outpost-1", transport_dest="not-a-hash"
        )


def test_claim_outpost_rejects_reused_code(pairing_with_corkboard: PairingService):
    created = pairing_with_corkboard.create_code("aj")
    pairing_with_corkboard.redeem_outpost_code(
        code=created["code"], node_id="outpost-1", transport_dest="aa" * 16
    )
    with pytest.raises(ValueError, match="already used"):
        pairing_with_corkboard.redeem_outpost_code(
            code=created["code"], node_id="outpost-2", transport_dest="bb" * 16
        )


async def test_handle_outpost_claim_rpc_round_trip(pairing_with_corkboard: PairingService):
    created = pairing_with_corkboard.create_code("aj")
    env = Envelope(
        src="outpost-1",
        dst="station",
        svc=SVC_CORKBOARD,
        op=OP_OUTPOST_CLAIM,
        flags=int(Flags.REQUEST),
        payload={"code": created["code"], "transport_dest": "cc" * 16},
    )
    reply = await pairing_with_corkboard.handle_outpost_claim(env)
    assert not (reply.flags & int(Flags.ERROR))
    assert reply.payload["ok"] is True
    assert pairing_with_corkboard.transport.routes["outpost-1"] == "cc" * 16


def test_redeem_code_learns_route_when_transport_dest_given(tmp_path: Path):
    """Regression: the radio PAIR_REDEEM path accepted transport_dest but
    never called learn_route, so a freshly-pairing device's own reply
    couldn't be sent back to it."""
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch)
    svc = PairingService(db, dispatch)
    svc.transport = _StubTransport()

    created = svc.create_code("carol")
    svc.redeem_code(
        code=created["code"], node_id="pocket-carol", transport_dest="dd" * 16
    )
    assert svc.transport.routes["pocket-carol"] == "dd" * 16


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
