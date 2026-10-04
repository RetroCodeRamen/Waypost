"""Scout identity over radio: WHOAMI, PAIR_REDEEM reply size, and who may
claim to be the sender of a Dispatch message."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.db import Database
from server.services.auth.pairing import PairingService
from server.services.dispatch.constants import OP_MSG_SEND
from server.services.dispatch.service import DispatchService
from server.services.profiles.constants import OP_PAIR_REDEEM, OP_UNPAIR, OP_WHOAMI
from shared.protocol.envelope import SVC_DISPATCH, SVC_PROFILE, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

SCOUT = "pocket-1-e75a"
SCOUT_DEST = "e75a4c2818b4cd84b800d98827a11ed9"


@pytest.fixture()
def svc(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(
        db.dispatch, is_trusted_courier=lambda n: n == "outpost-1"
    )
    return db, dispatch, PairingService(db, dispatch)


def _env(src: str, svc_id: str, op: str, payload: dict) -> Envelope:
    return Envelope(src=src, dst="station", svc=svc_id, op=op, flags=int(Flags.REQUEST), payload=payload)


async def test_whoami_unpaired_then_paired(svc):
    db, _dispatch, pairing = svc
    r = await pairing.handle_rpc(_env(SCOUT, SVC_PROFILE, OP_WHOAMI, {}))
    assert r.flags & Flags.ERROR and r.payload["error"] == "not_paired"

    db.ensure_user("aj", "AJ")
    code = pairing.create_code("aj")["code"]
    redeemed = await pairing.handle_rpc(
        _env(SCOUT, SVC_PROFILE, OP_PAIR_REDEEM, {"code": code, "node_id": SCOUT, "transport_dest": SCOUT_DEST})
    )
    assert redeemed.payload["ok"] and redeemed.payload["username"] == "aj"
    assert len(encode_cbor(redeemed)) <= RADIO_MDU

    me = await pairing.handle_rpc(_env(SCOUT, SVC_PROFILE, OP_WHOAMI, {}))
    assert me.payload == {"username": "aj", "display_name": "AJ"}
    assert len(encode_cbor(me)) <= RADIO_MDU


async def test_unpair_revokes_only_the_sender_and_is_idempotent(svc):
    _db, dispatch, pairing = svc
    dispatch.bind_device(SCOUT, "aj")
    dispatch.bind_device("pocket-2-beef", "aj")
    r = await pairing.handle_rpc(_env(SCOUT, SVC_PROFILE, OP_UNPAIR, {"node_id": "pocket-2-beef"}))
    assert r.payload == {"ok": True}
    assert dispatch.store.get_binding(SCOUT) is None
    assert dispatch.store.get_binding("pocket-2-beef")["username"] == "aj"  # payload ignored
    again = await pairing.handle_rpc(_env(SCOUT, SVC_PROFILE, OP_UNPAIR, {}))
    assert again.payload == {"ok": True}


async def test_bound_scout_sends_as_itself(svc):
    _db, dispatch, _pairing = svc
    dispatch.bind_device(SCOUT, "aj")
    r = await dispatch.handle_rpc(_env(SCOUT, SVC_DISPATCH, OP_MSG_SEND, {"peer": "bob", "body": "hi"}))
    assert r.payload["ok"]
    msgs = dispatch.list_messages(r.payload["conversation_id"])
    assert msgs[-1]["sender"] == "aj"


async def test_bound_scout_cannot_claim_another_sender(svc):
    _db, dispatch, _pairing = svc
    dispatch.bind_device(SCOUT, "aj")
    r = await dispatch.handle_rpc(
        _env(SCOUT, SVC_DISPATCH, OP_MSG_SEND, {"sender": "bob", "peer": "carol", "body": "spoof"})
    )
    assert r.flags & Flags.ERROR and r.payload["error"] == "sender_mismatch"


async def test_unbound_radio_rejected(svc):
    _db, dispatch, _pairing = svc
    r = await dispatch.handle_rpc(
        _env("pocket-9-ffff", SVC_DISPATCH, OP_MSG_SEND, {"sender": "aj", "peer": "bob", "body": "hi"})
    )
    assert r.flags & Flags.ERROR and r.payload["error"] == "unauthorized_device"


async def test_claimed_outpost_may_relay_someone_elses_message(svc):
    _db, dispatch, _pairing = svc
    r = await dispatch.handle_rpc(
        _env("outpost-1", SVC_DISPATCH, OP_MSG_SEND, {"sender": "aj", "peer": "bob", "body": "relayed"})
    )
    assert r.payload["ok"]
    unclaimed = await dispatch.handle_rpc(
        _env("outpost-2", SVC_DISPATCH, OP_MSG_SEND, {"sender": "aj", "peer": "bob", "body": "nope"})
    )
    assert unclaimed.payload["error"] == "unauthorized_device"
