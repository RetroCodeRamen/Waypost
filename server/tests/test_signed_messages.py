"""Signed Dispatch messages (roadmap D3, reworked 2026-10-05): signed with
the author's identity key (derived from username + password); Station
checks the signature against the key it has vouched for, so the author is
proven whoever carried the message.

The pinned object vector is also checked by the Scout at boot
(firmware/pocket/src/certs.cpp self_test)."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.db import Database
from server.services.dispatch.service import DispatchService
from server.services.dispatch.store import direct_conversation_id
from server.services.identity import certs as C
from server.services.identity import keys as K
from server.services.identity import objects as O
from server.services.identity.service import IdentityService
from shared.protocol.envelope import SVC_DISPATCH, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

SCOUT = "pocket-1-e75a"
T = 1_791_000_000
PASSWORD = "ridgeline long passphrase"


@pytest.fixture()
def world(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch, user_exists=lambda u: db.get_user_by_username(u) is not None)
    ident = IdentityService(db.identity, C.CommunityKey.generate(), get_binding=db.dispatch.get_binding,
                            get_user=db.get_user_by_username)
    dispatch.set_object_verifier(ident.verify_object)
    dispatch.set_author_lookup(ident.owner_of)
    db.ensure_user("ridgeline", "Ridgeline")
    db.ensure_user("basecamp", "Basecamp")
    ident.record_password("ridgeline", PASSWORD)
    dispatch.bind_device(SCOUT, "ridgeline", transport_dest="e75a" * 8)
    signing = K.private_key("ridgeline", PASSWORD)
    return db, dispatch, ident, signing, K.identity_id(K.public_key("ridgeline", PASSWORD))


def signed_send(signing, ident, body, *, peer=None, conv=None, author="ridgeline", oid=None, src=SCOUT, ts=T):
    oid = oid or O.new_oid()
    v = conv or direct_conversation_id(author, peer)
    sig = signing.sign(O.canonical_bytes(
        {"k": O.KIND_DISPATCH_MSG, "o": oid, "u": author, "a": ident, "v": v, "b": body, "t": ts}))
    payload = {"o": oid, "b": body, "a": ident, "s": sig}
    payload["p" if peer else "v"] = peer or conv
    return Envelope(src=src, dst="station", svc=SVC_DISPATCH, op="MSG_SEND", flags=int(Flags.REQUEST),
                    ts=ts, payload=payload), oid


async def test_signed_direct_message_is_stored_with_its_signature(world):
    db, dispatch, _i, signing, ident = world
    env, oid = signed_send(signing, ident, "  water's on at the north tap  ", peer="basecamp")
    r = await dispatch.handle_rpc(env)
    assert r.payload["ok"] and r.payload["signed"] and r.payload["id"] == oid.hex()
    msg = db.dispatch.get_message(oid.hex())
    assert msg["sender"] == "ridgeline" and msg["conversation_id"] == "dm:basecamp:ridgeline"
    assert msg["body"] == "  water's on at the north tap  "  # exactly as signed
    assert msg["author_id"] == ident.hex() and msg["signed_at"] == T and len(msg["sig"]) == 128
    again = await dispatch.handle_rpc(signed_send(signing, ident, "  water's on at the north tap  ",
                                                  peer="basecamp", oid=oid)[0])
    assert again.payload["ok"] and not again.payload["created"]


async def test_any_node_may_carry_a_signed_message(world):
    """The author is proven by the signature, not by who delivered it."""
    db, dispatch, _i, signing, ident = world
    env, oid = signed_send(signing, ident, "carried by a stranger", peer="basecamp", src="pocket-9-courier")
    r = await dispatch.handle_rpc(env)
    assert r.payload["ok"] and db.dispatch.get_message(oid.hex())["sender"] == "ridgeline"


async def test_tampering_and_impersonation_fail(world):
    _db, dispatch, _i, signing, ident = world
    env, _ = signed_send(signing, ident, "meet at noon", peer="basecamp")
    env.payload["b"] = "meet at midnight"
    assert (await dispatch.handle_rpc(env)).payload["error"] == "bad_signature"
    # Signed as if from basecamp with ridgeline's identity: the conversation
    # id won't match whose identity it is.
    env, _ = signed_send(signing, ident, "hi", conv="dm:basecamp:carol", author="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "bad_signature"
    # Same username, wrong password = a different key: not ridgeline.
    impostor = K.private_key("ridgeline", "guessed wrong password")
    env, _ = signed_send(impostor, ident, "forged", peer="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "bad_signature"
    env, _ = signed_send(impostor, K.identity_id(K.public_key("ridgeline", "guessed wrong password")),
                         "unknown key", peer="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "unknown_identity"


async def test_a_replaced_key_can_no_longer_sign(world):
    _db, dispatch, ident_svc, signing, ident = world
    ident_svc.record_password("ridgeline", "changed my passphrase")
    env, _ = signed_send(signing, ident, "with the old password", peer="basecamp")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "identity_revoked"


async def test_signed_message_to_unknown_person(world):
    _db, dispatch, _i, signing, ident = world
    env, _ = signed_send(signing, ident, "hello?", peer="nobody")
    assert (await dispatch.handle_rpc(env)).payload["error"] == "unknown_user"


async def test_signed_send_and_reply_fit_one_packet(world):
    _db, dispatch, _i, signing, ident = world
    from server.services.sync.engine import max_signed_body

    env, _ = signed_send(signing, ident, "x" * max_signed_body("basecamp"), peer="basecamp")
    assert len(encode_cbor(env)) <= RADIO_MDU
    r = await dispatch.handle_rpc(env)
    assert len(encode_cbor(r)) <= RADIO_MDU


# -- pinned vector (the Scout checks the same) -------------------------------------

VECTOR_OBJECT = {"k": "dispatch.msg", "o": bytes(range(16)), "u": "aj", "a": bytes(range(16, 32)),
                 "v": "dm:aj:bob", "b": "hello", "t": 1790000000}
VECTOR_OBJECT_SIG = (
    "05619c34b899c57d550f7faa3676f1b35bd12a2e9bb089d2c4e791624747f433"
    "7b714cb9caf2e1ad73583e7ba1d33e70dc0d1831835e29a5118777965795c40f"
)


def test_pinned_object_vector():
    key = C.CommunityKey.from_seed(bytes(range(32)))  # same seed as the certificate vector
    sig = key._private.sign(O.canonical_bytes(VECTOR_OBJECT))
    assert sig.hex() == VECTOR_OBJECT_SIG
