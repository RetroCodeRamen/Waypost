"""Offline identity: Station's community key vouches for each person's
identity key (derived from username + password) with an ``id``
certificate; replaced keys are revoked. Every reply fits one packet.

The pinned vector at the bottom is also checked by the Scout firmware
(firmware/pocket/src/certs.cpp, self-test at boot) so Python and C++ can't
drift apart on the canonical bytes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.db import Database
from server.services.dispatch.service import DispatchService
from server.services.identity import certs as C
from server.services.identity import keys as K
from server.services.identity.service import IdentityService
from server.services.profiles.constants import OP_CERT_GET, OP_CERT_LIST, OP_CERT_REVOKED, OP_CERT_ROOT
from shared.protocol.envelope import SVC_PROFILE, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

SCOUT = "pocket-1-e75a"


class Clock:
    def __init__(self) -> None:
        self.t = 1_790_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def world(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch)
    clock = Clock()
    key = C.CommunityKey.load_or_create(tmp_path / "community.key")
    ident = IdentityService(db.identity, key, get_binding=db.dispatch.get_binding,
                            get_user=db.get_user_by_username, clock=clock)
    for user, name in (("ridgeline", "Ridgeline Scout"), ("basecamp", "Basecamp")):
        db.ensure_user(user, name)
        ident.record_password(user, f"{user} long passphrase")
    dispatch.bind_device(SCOUT, "ridgeline", transport_dest="e75a" * 8)
    return db, dispatch, ident, key, clock


def _env(op: str, payload: dict, src: str = SCOUT) -> Envelope:
    return Envelope(src=src, dst="station", svc=SVC_PROFILE, op=op, flags=int(Flags.REQUEST), payload=payload)


def _fits(env: Envelope) -> bool:
    return len(encode_cbor(env)) <= RADIO_MDU


def test_key_file_is_private_and_stable(tmp_path):
    path = tmp_path / "k" / "community.key"
    a = C.CommunityKey.load_or_create(path)
    b = C.CommunityKey.load_or_create(path)
    assert a.public_bytes == b.public_bytes
    assert path.stat().st_mode & 0o777 == 0o600


async def test_root_is_public(world):
    _db, _d, ident, key, _c = world
    r = await ident.handle_rpc(_env(OP_CERT_ROOT, {}, src="pocket-9-stranger"))
    assert r.payload["pk"] == key.public_bytes and _fits(r)


async def test_identity_cert_by_name_and_by_id(world):
    _db, _d, ident, key, _c = world
    r = await ident.handle_rpc(_env(OP_CERT_GET, {"u": "basecamp"}))
    assert _fits(r), len(encode_cbor(r))
    cert = r.payload["cert"]
    assert cert["k"] == "id" and cert["dn"] == "Basecamp"
    assert cert["p"] == K.public_key("basecamp", "basecamp long passphrase")
    assert cert["i"] == K.identity_id(cert["p"]) and C.verify(cert, key.public_bytes)
    by_id = await ident.handle_rpc(_env(OP_CERT_GET, {"i": cert["i"]}))
    assert by_id.payload["cert"]["n"] == cert["n"]
    me = await ident.handle_rpc(_env(OP_CERT_GET, {}))
    assert me.payload["cert"]["u"] == "ridgeline"


async def test_lookups_that_fail(world):
    db, _d, ident, _k, _c = world
    assert (await ident.handle_rpc(_env(OP_CERT_GET, {"u": "nobody"}))).payload["error"] == "unknown_user"
    db.ensure_user("oldtimer", "Old Timer")  # never signed in since keys came in
    assert (await ident.handle_rpc(_env(OP_CERT_GET, {"u": "oldtimer"}))).payload["error"] == "no_identity_yet"
    assert (await ident.handle_rpc(_env(OP_CERT_GET, {"i": bytes(16)}))).payload["error"] == "unknown_identity"
    r = await ident.handle_rpc(_env(OP_CERT_GET, {}, src="pocket-9-x"))
    assert r.payload["error"] == "unauthorized_device"


async def test_long_display_name_still_fits(world):
    db, _d, ident, _k, _c = world
    db.ensure_user("longname", "Ünïcode camper with a really very long display name indeed")
    ident.record_password("longname", "a long enough passphrase")
    r = await ident.handle_rpc(_env(OP_CERT_GET, {"u": "longname"}))
    assert _fits(r) and len(r.payload["cert"]["dn"].encode()) <= C.MAX_DISPLAY_NAME


async def test_replaced_key_is_revoked_and_revocations_page(world):
    _db, _d, ident, key, _c = world
    old = (await ident.handle_rpc(_env(OP_CERT_GET, {"u": "basecamp"}))).payload["cert"]
    ident.record_password("basecamp", "a brand new passphrase")
    r = await ident.handle_rpc(_env(OP_CERT_REVOKED, {}))
    assert _fits(r)
    (rev,) = r.payload["revs"]
    assert rev["r"] == old["n"] and C.verify(rev, key.public_bytes)
    gone = await ident.handle_rpc(_env(OP_CERT_GET, {"i": old["i"]}))
    assert gone.payload["error"] == "unknown_identity"


async def test_certificates_renew_near_expiry(world):
    _db, _d, ident, _k, clock = world
    first = (await ident.handle_rpc(_env(OP_CERT_GET, {}))).payload["cert"]
    clock.t += 24 * 24 * 3600  # 6 days left
    renewed = (await ident.handle_rpc(_env(OP_CERT_GET, {}))).payload["cert"]
    assert renewed["n"] != first["n"] and renewed["i"] == first["i"] and renewed["p"] == first["p"]


async def test_outposts_page_through_everyone(world):
    db, _d, ident, key, _c = world
    for i in range(12):
        db.ensure_user(f"camper{i:02d}", f"Camper {i:02d}")
        ident.record_password(f"camper{i:02d}", "camper long passphrase")
    ident._is_claimed_outpost = lambda node: node == "outpost-1-00a1"
    seen, offset = [], 0
    while True:
        r = await ident.handle_rpc(_env(OP_CERT_LIST, {"offset": offset}, src="outpost-1-00a1"))
        assert _fits(r)
        seen += r.payload["certs"]
        offset += len(r.payload["certs"])
        if not r.payload["more"]:
            break
    assert len(seen) == 14 and all(C.verify(c, key.public_bytes) for c in seen)
    r = await ident.handle_rpc(_env(OP_CERT_LIST, {}, src="outpost-9-unclaimed"))
    assert r.payload["error"] == "unauthorized_device"


def test_tampered_certificate_fails():
    key = C.CommunityKey.from_seed(bytes(32))
    cert = key.sign({"k": "id", "n": 1, "i": bytes(16), "u": "aj", "dn": "AJ", "p": bytes(32), "t": 1, "x": 2})
    assert C.verify(cert, key.public_bytes)
    assert not C.verify(dict(cert, u="bob"), key.public_bytes)
    assert not C.verify(dict(cert, p=b"\x01" * 32), key.public_bytes)
    assert not C.verify(cert, C.CommunityKey.from_seed(b"\x01" * 32).public_bytes)


# -- the vector the firmware checks too ------------------------------------------

VECTOR_SEED = bytes(range(32))
VECTOR_CERT = {"k": "id", "n": 7, "i": bytes(range(16)), "u": "aj", "dn": "AJ", "p": bytes(range(32, 64)),
               "t": 1790000000, "x": 1792592000}
VECTOR_PUBLIC = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
VECTOR_SIG = (
    "324aa31e6a2464e5564dbd9104bd140eaeb306dc52badaf0adfcd3152407f402"
    "b2546d77e98676476409d3d5d3c49511a744e8a65564b0978e14ab10885b1804"
)


def test_pinned_vector():
    key = C.CommunityKey.from_seed(VECTOR_SEED)
    signed = key.sign(VECTOR_CERT)
    canon = C.canonical_bytes(VECTOR_CERT)
    assert canon.startswith(b"WAYPOST-CERT-1\nk:\x00\x02idn:\x00\x08\x00\x00\x00\x00\x00\x00\x00\x07")
    assert key.public_bytes.hex() == VECTOR_PUBLIC
    assert signed["s"].hex() == VECTOR_SIG
