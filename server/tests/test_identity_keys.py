"""Identity keys from username + password (2026-10-05, docs/identity.md),
recorded by Station wherever it sees a password, and Scout login by signing
a one-time challenge with the derived key — the password never crosses the
radio. The pinned vector is also checked by the Scout (certs.cpp self-test)
and the Outpost's web page."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.db import Database
from server.services.auth.pairing import PairingService
from server.services.auth.service import AuthService
from server.services.dispatch.service import DispatchService
from server.services.identity import certs as C
from server.services.identity import keys as K
from server.services.identity.service import IdentityService
from server.services.profiles.constants import OP_LOGIN, OP_LOGIN_NONCE
from shared.protocol.envelope import SVC_PROFILE, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

SCOUT = "pocket-1-e75a"
DEST = bytes.fromhex("e75a4c2818b4cd84b800d98827a11ed9")
PASSWORD = "blue canoe river"
VECTOR_SEED = "0bfde6e3b8b2a6f55eb9e13e94c483df0a5feb350e939a840240c8e241d2c2e6"
VECTOR_PUBLIC = "c429d72f6ecb1bb2ce838d07e4cb8e1e757a52a78560b1b822e3c267533e6708"
VECTOR_ID = "c7a7953330f8c28e3ba64498b3e9f6da"


@pytest.fixture()
def world(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch)
    ident = IdentityService(db.identity, C.CommunityKey.generate(), get_binding=db.dispatch.get_binding,
                            get_user=db.get_user_by_username)
    auth = AuthService(db)
    auth.on_password = ident.record_password
    pairing = PairingService(db, dispatch)
    pairing.identity = ident
    return db, dispatch, ident, auth, pairing


def test_pinned_vector():
    assert K.derive_seed("Basecamp", PASSWORD).hex() == VECTOR_SEED
    assert K.derive_seed(" basecamp ", PASSWORD).hex() == VECTOR_SEED  # usernames are case/space-blind
    pub = K.public_key("basecamp", PASSWORD)
    assert pub.hex() == VECTOR_PUBLIC and K.identity_id(pub).hex() == VECTOR_ID
    assert K.public_key("basecamp", PASSWORD + "!") != pub  # another password, another person


def test_registration_and_sign_in_record_the_key(world):
    _db, _d, ident, auth, _p = world
    auth.register(username="basecamp", password=PASSWORD)
    cert = ident.identity_cert("basecamp")
    assert cert["p"] == K.public_key("basecamp", PASSWORD) and cert["i"] == K.identity_id(cert["p"])
    auth.login(username="basecamp", password=PASSWORD)
    assert ident.identity_cert("basecamp")["n"] == cert["n"]  # same key: same certificate


def test_a_new_password_is_a_new_identity_and_the_old_one_is_revoked(world):
    _db, _d, ident, auth, _p = world
    auth.register(username="basecamp", password=PASSWORD)
    old = ident.identity_cert("basecamp")
    ident.record_password("basecamp", "a different passphrase")
    new = ident.identity_cert("basecamp")
    assert new["i"] != old["i"]
    assert [r["r"] for r in ident.revocations()] == [old["n"]]
    assert ident.cert_for_id(old["i"]) is None and ident.cert_for_id(new["i"])["u"] == "basecamp"


def _env(op, payload, src=SCOUT):
    return Envelope(src=src, dst="station", svc=SVC_PROFILE, op=op, flags=int(Flags.REQUEST), payload=payload)


async def _login(pairing, username, password, *, src=SCOUT):
    nonce = (await pairing.handle_rpc(_env(OP_LOGIN_NONCE, {}, src=src))).payload["nonce"]
    sig = K.private_key(username, password).sign(PairingService.login_bytes(src, DEST, nonce))
    env = _env(OP_LOGIN, {"u": username, "rd": DEST, "sig": sig}, src=src)
    assert len(encode_cbor(env)) <= RADIO_MDU
    return await pairing.handle_rpc(env)


async def test_scout_login_binds_the_scout(world):
    db, _d, _i, auth, pairing = world
    auth.register(username="basecamp", password=PASSWORD)
    r = await _login(pairing, "basecamp", PASSWORD)
    assert r.payload["ok"] and r.payload["username"] == "basecamp"
    binding = db.dispatch.get_binding(SCOUT)
    assert binding["username"] == "basecamp" and binding["transport_dest"] == DEST.hex()


async def test_scout_login_refusals(world):
    db, _d, _i, auth, pairing = world
    auth.register(username="basecamp", password=PASSWORD)
    assert (await _login(pairing, "basecamp", "not the password")).payload["error"] == "wrong_password"
    assert (await _login(pairing, "nobody", PASSWORD)).payload["error"] == "unknown_user"
    db.ensure_user("oldtimer", "Old Timer")  # account from before keys: never signed in since
    assert (await _login(pairing, "oldtimer", PASSWORD)).payload["error"] == "no_identity_yet"
    # A signature is only good for its own challenge.
    nonce = (await pairing.handle_rpc(_env(OP_LOGIN_NONCE, {}))).payload["nonce"]
    sig = K.private_key("basecamp", PASSWORD).sign(PairingService.login_bytes(SCOUT, DEST, nonce))
    await pairing.handle_rpc(_env(OP_LOGIN_NONCE, {}))  # a new challenge replaces it
    r = await pairing.handle_rpc(_env(OP_LOGIN, {"u": "basecamp", "rd": DEST, "sig": sig}))
    assert r.payload["error"] == "wrong_password"
    assert db.dispatch.get_binding(SCOUT) is None
