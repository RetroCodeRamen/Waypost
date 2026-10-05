"""Signed Dispatch messages (roadmap D3): authored and signed on the device
with its signing key; Station checks the signature against the device
certificate, so the author is proven whoever carried the message.

The pinned object vector is also checked by the Scout at boot
(firmware/pocket/src/certs.cpp self_test)."""

from __future__ import annotations

from pathlib import Path

import pytest
import RNS
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from server.api.db import Database
from server.services.dispatch.service import DispatchService
from server.services.identity import certs as C
from server.services.identity import objects as O
from server.services.identity.service import IdentityService, waylink_dest_hex
from shared.protocol.envelope import SVC_DISPATCH, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

SCOUT = "pocket-1-e75a"
T = 1_791_000_000


@pytest.fixture()
def world(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch, user_exists=lambda u: db.get_user_by_username(u) is not None)
    ident = IdentityService(db.identity, C.CommunityKey.generate(), get_binding=db.dispatch.get_binding,
                            get_user=db.get_user_by_username)
    dispatch.set_object_verifier(ident.verify_object)
    dispatch.set_cert_owner(db.identity.device_owner)
    db.ensure_user("ridgeline", "Ridgeline")
    db.ensure_user("basecamp", "Basecamp")
    net = RNS.Identity()
    dispatch.bind_device(SCOUT, "ridgeline", transport_dest=waylink_dest_hex(net.get_public_key())[0])
    signing = Ed25519PrivateKey.generate()
    spk = signing.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    cert = ident.issue_device_cert(node_id=SCOUT, username="ridgeline", signing_key=spk, device_hash=net.hash)
    return db, dispatch, ident, signing, cert


def signed_send(signing, cert, body, *, peer=None, conv=None, author="ridgeline", oid=None, src=SCOUT, ts=T):
    oid = oid or O.new_oid()
    from server.services.dispatch.store import direct_conversation_id

    v = conv or direct_conversation_id(author, peer)
    sig = signing.sign(O.canonical_bytes(
        {"k": O.KIND_DISPATCH_MSG, "o": oid, "u": author, "c": cert["n"], "v": v, "b": body, "t": ts}))
    payload = {"o": oid, "b": body, "c": cert["n"], "s": sig}
    payload["p" if peer else "v"] = peer or conv
    return Envelope(src=src, dst="station", svc=SVC_DISPATCH, op="MSG_SEND", flags=int(Flags.REQUEST),
                    ts=ts, payload=payload), oid


async def test_signed_direct_message_is_stored_with_its_signature(world):
    db, dispatch, _i, signing, cert = world
    env, oid = signed_send(signing, cert, "  water's on at the north tap  ", peer="basecamp")
    r = await dispatch.handle_rpc(env)
    assert r.payload["ok"] and r.payload["signed"] and r.payload["id"] == oid.hex()
    msg = db.dispatch.get_message(oid.hex())
    assert msg["sender"] == "ridgeline" and msg["conversation_id"] == "dm:basecamp:ridgeline"
    assert msg["body"] == "  water's on at the north tap  "  # exactly as signed
    assert msg["cert_serial"] == cert["n"] and msg["signed_at"] == T and len(msg["sig"]) == 128
    again = await dispatch.handle_rpc(signed_send(signing, cert, "  water's on at the north tap  ",
                                                  peer="basecamp", oid=oid)[0])
    assert again.payload["ok"] and not again.payload["created"]


async def test_any_node_may_carry_a_signed_message(world):
    """The author is proven by the signature, not by who delivered it."""
    db, dispatch, _i, signing, cert = world
    env, oid = signed_send(signing, cert, "carried by a stranger", peer="basecamp", src="pocket-9-courier")
    r = await dispatch.handle_rpc(env)
    assert r.payload["ok"] and db.dispatch.get_message(oid.hex())["sender"] == "ridgeline"


async def test_tampering_and_impersonation_fail(world):
    _db, dispatch, _i, signing, cert = world
    env, _ = signed_send(signing, cert, "meet at noon", peer="basecamp")
    env.payload["b"] = "meet at midnight"
    assert (await dispatch.handle_rpc(env)).payload["error"] == "bad_signature"
    # Signed as if from basecamp with ridgeline's certificate: the
    # conversation id won't match the certificate's owner.
    env, _ = signed_send(signing, cert, "hi", conv="dm:basecamp:carol", author="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "bad_signature"
    other = Ed25519PrivateKey.generate()
    env, _ = signed_send(other, cert, "forged", peer="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "bad_signature"
    env, _ = signed_send(signing, dict(cert, n=9999), "unknown cert", peer="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "unknown_certificate"


async def test_revoked_device_can_no_longer_sign(world):
    _db, dispatch, _i, signing, cert = world
    dispatch.unbind_device(SCOUT, username="ridgeline")
    env, _ = signed_send(signing, cert, "after unpairing", peer="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "certificate_revoked"


async def test_signed_message_to_unknown_person(world):
    _db, dispatch, _i, signing, cert = world
    env, _ = signed_send(signing, cert, "hello?", peer="nobody")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "unknown_user"


async def test_signed_send_and_reply_fit_one_packet(world):
    _db, dispatch, _i, signing, cert = world
    env, _ = signed_send(signing, cert, "x" * 133, peer="basecamp")
    assert len(encode_cbor(env)) <= RADIO_MDU
    r = await dispatch.handle_rpc(env)
    assert len(encode_cbor(r)) <= RADIO_MDU


# -- pinned vector (the Scout checks the same) -------------------------------------

VECTOR_OBJECT = {"k": "dispatch.msg", "o": bytes(range(16)), "u": "aj", "c": 7,
                 "v": "dm:aj:bob", "b": "hello", "t": 1790000000}
VECTOR_OBJECT_SIG = (
    "53a22849b552e78676b96d7a51b6d62477a42b297636c0fd1a52e490ae4f0110"
    "d9bf87ce722b3d2f6350571956570e103e0a928ed61be596d2c9935ee7e3ac0d"
)


def test_pinned_object_vector():
    key = C.CommunityKey.from_seed(bytes(range(32)))  # same seed as the certificate vector
    sig = key._private.sign(O.canonical_bytes(VECTOR_OBJECT))
    assert sig.hex() == VECTOR_OBJECT_SIG
