"""N2 account auth tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.db import Database
from server.api.main import create_app
from server.services.auth.service import AuthService


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


def _login_cookie_header(client: TestClient, url: str) -> str:
    r = client.post(url, json={"username": "aj", "password": "waypost1"})
    assert r.status_code == 200
    return r.headers["set-cookie"].lower()


def test_session_cookie_secure_only_over_https(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="development",
    )
    with TestClient(create_app(settings), base_url="https://waypost.home.arpa") as c:
        assert "; secure" in _login_cookie_header(c, "/api/auth/login")
    with TestClient(create_app(settings)) as c:
        assert "; secure" not in _login_cookie_header(c, "/api/auth/login")


def test_production_has_no_lab_users(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="production",
    )
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/auth/login", json={"username": "aj", "password": "waypost1"})
        assert r.status_code == 401
        assert c.get("/trust.html").status_code == 200


# -- M4: ADMIN_APPROVAL registration mode + admin role --

# Service-level: no lab-seeded aj/bob (those only exist via the app's
# lifespan), so the first registration in a fresh Database is genuinely
# the first user — the bootstrap-admin path this exercises.


@pytest.fixture()
def auth(tmp_path: Path) -> AuthService:
    db = Database(tmp_path / "test.db")
    return AuthService(db)


def test_first_user_bootstraps_as_admin_and_approved(auth: AuthService):
    result = auth.register(
        username="carol", password="secret123", registration_mode="ADMIN_APPROVAL"
    )
    assert "token" in result  # not pending — bootstrap admin skips approval
    assert result["user"]["is_admin"] is True
    assert result["user"]["approved"] is True


def test_second_user_pending_under_admin_approval(auth: AuthService):
    auth.register(username="carol", password="secret123", registration_mode="OPEN")
    result = auth.register(
        username="dave", password="secret123", registration_mode="ADMIN_APPROVAL"
    )
    assert result.get("pending_approval") is True
    assert "token" not in result
    assert result["user"]["is_admin"] is False
    assert result["user"]["approved"] is False

    with pytest.raises(ValueError, match="pending"):
        auth.login(username="dave", password="secret123")


def test_approval_unblocks_login(auth: AuthService):
    auth.register(username="carol", password="secret123", registration_mode="OPEN")
    auth.register(username="dave", password="secret123", registration_mode="ADMIN_APPROVAL")

    pending = auth.list_pending_users()
    assert [u["username"] for u in pending] == ["dave"]

    approved = auth.approve_user("dave")
    assert approved["approved"] is True

    result = auth.login(username="dave", password="secret123")
    assert "token" in result


def test_approving_twice_rejected(auth: AuthService):
    auth.register(username="carol", password="secret123", registration_mode="OPEN")
    auth.register(username="dave", password="secret123", registration_mode="ADMIN_APPROVAL")
    auth.approve_user("dave")
    with pytest.raises(ValueError, match="already approved"):
        auth.approve_user("dave")


def test_open_and_invite_only_modes_do_not_require_approval(auth: AuthService):
    result = auth.register(username="carol", password="secret123", registration_mode="OPEN")
    assert "token" in result
    # Second user, so not the bootstrap-admin path
    result2 = auth.register(username="dave", password="secret123", registration_mode="OPEN")
    assert "token" in result2
    assert result2["user"]["approved"] is True


# -- HTTP-level: routes, admin-only gating --


@pytest.fixture()
def admin_approval_client(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="production",  # no aj/bob lab seeding
        waypost_registration_mode="ADMIN_APPROVAL",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_http_register_pending_then_approve_flow(admin_approval_client: TestClient):
    c = admin_approval_client
    # First registrant bootstraps as admin, gets a session immediately.
    admin_reg = c.post(
        "/api/auth/register", json={"username": "carol", "password": "secret123"}
    )
    assert admin_reg.status_code == 200
    admin_token = admin_reg.json()["token"]

    # Second registrant is gated.
    pending_reg = c.post(
        "/api/auth/register", json={"username": "dave", "password": "secret123"}
    )
    assert pending_reg.status_code == 200
    assert pending_reg.json()["pending_approval"] is True
    assert "token" not in pending_reg.json()

    blocked_login = c.post(
        "/api/auth/login", json={"username": "dave", "password": "secret123"}
    )
    assert blocked_login.status_code == 401

    # A non-admin can't see or approve pending users.
    c.post("/api/auth/login", json={"username": "dave", "password": "secret123"})
    forbidden = c.get(
        "/api/auth/pending", headers={"Authorization": f"Bearer {admin_token}bad"}
    )
    assert forbidden.status_code == 401  # bad token entirely

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    listed = c.get("/api/auth/pending", headers=admin_headers)
    assert listed.status_code == 200
    assert [u["username"] for u in listed.json()["users"]] == ["dave"]

    approve = c.post(
        "/api/auth/approve", json={"username": "dave"}, headers=admin_headers
    )
    assert approve.status_code == 200

    now_login = c.post(
        "/api/auth/login", json={"username": "dave", "password": "secret123"}
    )
    assert now_login.status_code == 200


def test_non_admin_cannot_reach_admin_routes(admin_approval_client: TestClient):
    c = admin_approval_client
    c.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    dave_reg = c.post(
        "/api/auth/register", json={"username": "dave", "password": "secret123"}
    )
    assert dave_reg.json()["pending_approval"] is True

    admin_headers = {
        "Authorization": "Bearer "
        + c.post(
            "/api/auth/login", json={"username": "carol", "password": "secret123"}
        ).json()["token"]
    }
    c.post("/api/auth/approve", json={"username": "dave"}, headers=admin_headers)
    dave_token = c.post(
        "/api/auth/login", json={"username": "dave", "password": "secret123"}
    ).json()["token"]

    r = c.get("/api/auth/pending", headers={"Authorization": f"Bearer {dave_token}"})
    assert r.status_code == 403
