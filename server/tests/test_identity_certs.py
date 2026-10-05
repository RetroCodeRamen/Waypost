"""Offline identity (roadmap D2): certificates signed by Station's community
key, issued and served over PROFILE CERT_* ops; every reply fits one packet.

The pinned vector at the bottom is also checked by the Scout firmware
(firmware/pocket/src/certs.cpp, self-test at boot) so Python and C++ can't
drift apart on the canonical bytes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import RNS

from server.api.db import Database
from server.services.dispatch.service import DispatchService
from server.services.identity import certs as C
from server.services.identity.service import IdentityService, waylink_dest_hex
from server.services.profiles.constants import (
    OP_CERT_DEV,
    OP_CERT_GET,
    OP_CERT_ISSUE,
    OP_CERT_REVOKED,
    OP_CERT_ROOT,
)
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
    scout = RNS.Identity()
    dest, _ = waylink_dest_hex(scout.get_public_key())
    db.ensure_user("ridgeline", "Ridgeline Scout")
    dispatch.bind_device(SCOUT, "ridgeline", transport_dest=dest)
    return db, dispatch, ident, key, scout, clock


def _env(op: str, payload: dict, src: str = SCOUT) -> Envelope:
    return Envelope(src=src, dst="station", svc=SVC_PROFILE, op=op, flags=int(Flags.REQUEST), payload=payload)


def _fits(env: Envelope) -> bool:
    return len(encode_cbor(env)) <= RADIO_MDU


def _issue_payload(scout: RNS.Identity, spk: bytes, node_id: str = SCOUT) -> dict:
    return {"pk": scout.get_public_key(), "spk": spk,
            "sig": scout.sign(C.issue_request_bytes(node_id, spk))}


def test_key_file_is_private_and_stable(tmp_path):
    path = tmp_path / "k" / "community.key"
    a = C.CommunityKey.load_or_create(path)
    b = C.CommunityKey.load_or_create(path)
    assert a.public_bytes == b.public_bytes
    assert path.stat().st_mode & 0o777 == 0o600


async def test_root_is_public(world):
    _db, _d, ident, key, _s, _c = world
    r = await ident.handle_rpc(_env(OP_CERT_ROOT, {}, src="pocket-9-stranger"))
    assert r.payload["pk"] == key.public_bytes and _fits(r)


async def test_issue_device_cert_and_verify_offline(world):
    _db, _d, ident, key, scout, _c = world
    spk = bytes(range(32))
    r = await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, spk)))
    assert _fits(r), len(encode_cbor(r))
    cert = r.payload["cert"]
    assert cert["k"] == "dev" and cert["u"] == "ridgeline" and cert["p"] == spk
    assert cert["d"] == scout.hash
    assert C.verify(cert, key.public_bytes)
    # Same key again: the same certificate (no churn on every boot).
    again = await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, spk)))
    assert again.payload["cert"]["n"] == cert["n"]


async def test_issue_refuses_a_key_that_is_not_the_paired_device(world):
    _db, _d, ident, _k, scout, _c = world
    other = RNS.Identity()
    r = await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(other, bytes(32))))
    assert r.flags & Flags.ERROR and r.payload["error"] == "device_key_mismatch"
    forged = _issue_payload(scout, bytes(32))
    forged["sig"] = other.sign(C.issue_request_bytes(SCOUT, bytes(32)))
    r = await ident.handle_rpc(_env(OP_CERT_ISSUE, forged))
    assert r.payload["error"] == "bad_signature"
    r = await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, bytes(32)), src="pocket-9-x"))
    assert r.payload["error"] == "unauthorized_device"


async def test_identity_cert_and_devices_for_a_contact(world):
    db, dispatch, ident, key, scout, _c = world
    await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, bytes(32))))
    db.ensure_user("basecamp", "Basecamp")
    bob = RNS.Identity()
    dispatch.bind_device("pocket-1-b0b0", "basecamp", transport_dest=waylink_dest_hex(bob.get_public_key())[0])
    await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(bob, b"\x07" * 32, "pocket-1-b0b0"), src="pocket-1-b0b0"))

    r = await ident.handle_rpc(_env(OP_CERT_GET, {"u": "basecamp"}))
    assert _fits(r) and r.payload["devs"] == 1
    idc = r.payload["cert"]
    assert idc["k"] == "id" and idc["dn"] == "Basecamp" and C.verify(idc, key.public_bytes)
    d = await ident.handle_rpc(_env(OP_CERT_DEV, {"u": "basecamp", "i": 0}))
    assert _fits(d) and not d.payload["more"]
    assert d.payload["cert"]["p"] == b"\x07" * 32 and d.payload["cert"]["i"] == idc["i"]
    me = await ident.handle_rpc(_env(OP_CERT_GET, {}))
    assert me.payload["cert"]["u"] == "ridgeline"
    assert (await ident.handle_rpc(_env(OP_CERT_GET, {"u": "nobody"}))).payload["error"] == "unknown_user"


async def test_long_display_name_still_fits(world):
    db, _d, ident, _k, _s, _c = world
    db.ensure_user("longname", "Ünïcode camper with a really very long display name indeed")
    r = await ident.handle_rpc(_env(OP_CERT_GET, {"u": "longname"}))
    assert _fits(r) and len(r.payload["cert"]["dn"].encode()) <= C.MAX_DISPLAY_NAME


async def test_unpairing_revokes_and_revocations_page(world):
    _db, dispatch, ident, key, scout, _c = world
    r = await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, bytes(32))))
    serial = r.payload["cert"]["n"]
    # A second device so someone is still paired to ask for the list.
    other = RNS.Identity()
    dispatch.bind_device("pocket-1-0002", "ridgeline", transport_dest=waylink_dest_hex(other.get_public_key())[0])
    dispatch.unbind_device(SCOUT, username="ridgeline")
    revs = (await ident.handle_rpc(_env(OP_CERT_REVOKED, {}, src="pocket-1-0002"))).payload["revs"]
    assert [x["r"] for x in revs] == [serial]
    assert C.verify(revs[0], key.public_bytes)
    devs = await ident.handle_rpc(_env(OP_CERT_DEV, {"u": "ridgeline", "i": 0}, src="pocket-1-0002"))
    assert devs.payload["cert"] is None


async def test_new_signing_key_revokes_the_old_one(world):
    _db, _d, ident, _k, scout, _c = world
    old = (await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, bytes(32))))).payload["cert"]
    new = (await ident.handle_rpc(_env(OP_CERT_ISSUE, _issue_payload(scout, b"\x01" * 32)))).payload["cert"]
    assert new["n"] != old["n"]
    revs = (await ident.handle_rpc(_env(OP_CERT_REVOKED, {}))).payload["revs"]
    assert [x["r"] for x in revs] == [old["n"]]


async def test_certificates_renew_near_expiry(world):
    _db, _d, ident, _k, scout, clock = world
    first = (await ident.handle_rpc(_env(OP_CERT_GET, {}))).payload["cert"]
    clock.t += 24 * 24 * 3600  # 6 days left
    renewed = (await ident.handle_rpc(_env(OP_CERT_GET, {}))).payload["cert"]
    assert renewed["n"] != first["n"] and renewed["i"] == first["i"]


def test_tampered_certificate_fails():
    key = C.CommunityKey.from_seed(bytes(32))
    cert = key.sign({"k": "id", "n": 1, "i": bytes(16), "u": "aj", "dn": "AJ", "t": 1, "x": 2})
    assert C.verify(cert, key.public_bytes)
    assert not C.verify(dict(cert, u="bob"), key.public_bytes)
    assert not C.verify(cert, C.CommunityKey.from_seed(b"\x01" * 32).public_bytes)


# -- the vector the firmware checks too ------------------------------------------

VECTOR_SEED = bytes(range(32))
VECTOR_CERT = {"k": "dev", "n": 7, "i": bytes(range(16)), "u": "aj", "p": bytes(range(32, 64)),
               "d": bytes(range(64, 80)), "t": 1790000000, "x": 1792592000}
VECTOR_PUBLIC = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
VECTOR_SIG = (
    "d28a4d7bccc832b97d1e63ec0082f293cdc75d2c6d0534ae8d0d525427e5f53c"
    "ecb30dd2c141c76893a0512195bd67d8b221cd8fda9234da007df8ac98abbd03"
)


def test_pinned_vector():
    key = C.CommunityKey.from_seed(VECTOR_SEED)
    signed = key.sign(VECTOR_CERT)
    canon = C.canonical_bytes(VECTOR_CERT)
    assert canon.startswith(b"WAYPOST-CERT-1\nk:\x00\x03devn:\x00\x08\x00\x00\x00\x00\x00\x00\x00\x07")
    assert key.public_bytes.hex() == VECTOR_PUBLIC
    assert signed["s"].hex() == VECTOR_SIG
