"""Scout contacts + conversations over radio: ROLL_LIST, MSG_CONVS, radio-sized
MSG_LIST, MSG_SYNC paging that can't lose messages, and pushes that fit.

Every reply a Scout asks for must fit one encrypted Reticulum packet
(shared/protocol/radio.py) — checked on every reply here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.db import Database
from server.services.dispatch.constants import OP_MSG_CONVS, OP_MSG_LIST, OP_MSG_SYNC
from server.services.dispatch.service import DispatchService
from server.services.profiles.constants import OP_ROLL_LIST
from server.services.profiles.rollcall import RollcallService
from shared.protocol.envelope import SVC_DISPATCH, SVC_PROFILE, Envelope, Flags, encode_cbor
from shared.protocol.radio import RADIO_MDU

SCOUT = "pocket-1-e75a"
LONG = "Water at the north tap is safe again — boil anyway for babies. " * 8  # ~500 bytes


@pytest.fixture()
def world(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    dispatch = DispatchService(db.dispatch)
    rollcall = RollcallService(
        db.rollcall,
        get_user=db.get_user_by_username,
        ensure_user=db.ensure_user,
        set_user_status=db.set_user_status,
        list_users=db.list_users,
        nodes_for_user=db.dispatch.nodes_for_user,
        get_binding=db.dispatch.get_binding,
        bindings_for_user=db.dispatch.list_bindings_for_user,
    )
    db.ensure_user("aj", "AJ")
    dispatch.bind_device(SCOUT, "aj", transport_dest="e75a4c2818b4cd84b800d98827a11ed9")
    return db, dispatch, rollcall


def _env(svc: str, op: str, payload: dict, src: str = SCOUT) -> Envelope:
    return Envelope(src=src, dst="station", svc=svc, op=op, flags=int(Flags.REQUEST), payload=payload)


def _fits(env: Envelope) -> bool:
    return len(encode_cbor(env)) <= RADIO_MDU


# -- ROLL_LIST ---------------------------------------------------------------


def test_roll_list_pages_everyone_but_me_with_scout_addresses(world):
    db, dispatch, rollcall = world
    for i in range(15):
        db.ensure_user(f"camper{i:02d}", f"Camper number {i:02d} with a longish name")
    dispatch.bind_device("pocket-1-b0b0", "camper03", transport_dest="b0b0" * 8)

    seen, offset = [], 0
    while True:
        r = rollcall.handle_rpc(_env(SVC_PROFILE, OP_ROLL_LIST, {"offset": offset}))
        assert _fits(r)
        people = r.payload["people"]
        seen += people
        offset += len(people)
        if not r.payload["more"]:
            break
    names = [p["u"] for p in seen]
    assert "aj" not in names and len(names) == len(set(names)) == 15
    assert next(p for p in seen if p["u"] == "camper03")["d"] == "b0b0" * 8
    assert next(p for p in seen if p["u"] == "camper04")["d"] == ""


def test_roll_list_requires_a_paired_device(world):
    _db, _dispatch, rollcall = world
    r = rollcall.handle_rpc(_env(SVC_PROFILE, OP_ROLL_LIST, {}, src="pocket-9-dead"))
    assert r.flags & Flags.ERROR and r.payload["error"] == "unauthorized_device"


# -- MSG_CONVS / MSG_LIST --------------------------------------------------------


async def test_convs_titles_and_size(world):
    _db, dispatch, _rollcall = world
    dispatch.send_direct(sender="bob", peer="aj", body="hi")
    dispatch.create_room(title="Kitchen crew", members=["aj", "bob", "carol"])
    r = await dispatch.handle_rpc(_env(SVC_DISPATCH, OP_MSG_CONVS, {}))
    assert _fits(r)
    titles = {c["t"] for c in r.payload["conversations"]}
    assert {"bob", "Kitchen crew"} <= titles


async def test_msg_list_members_only(world):
    _db, dispatch, _rollcall = world
    dispatch.send_direct(sender="bob", peer="carol", body="private")
    r = await dispatch.handle_rpc(_env(SVC_DISPATCH, OP_MSG_LIST, {"conversation_id": "dm:bob:carol"}))
    assert r.flags & Flags.ERROR and r.payload["error"] == "not_a_member"
    unbound = await dispatch.handle_rpc(
        _env(SVC_DISPATCH, OP_MSG_LIST, {"conversation_id": "dm:aj:bob"}, src="pocket-9-dead")
    )
    assert unbound.payload["error"] == "unauthorized_device"


async def test_msg_list_pages_newest_first_and_cuts_long_bodies(world):
    _db, dispatch, _rollcall = world
    for i in range(12):
        dispatch.send_direct(sender="bob" if i % 2 else "aj", peer="aj" if i % 2 else "bob", body=f"msg {i} " + ("x" * 60))
    dispatch.send_direct(sender="bob", peer="aj", body=LONG)

    got = []
    while True:
        r = await dispatch.handle_rpc(
            _env(SVC_DISPATCH, OP_MSG_LIST, {"peer": "bob", "skip": len(got)})
        )
        assert _fits(r)
        page = r.payload["messages"]
        got += page
        if not r.payload["more"] or not page:
            break
    assert len(got) == len({m["id"] for m in got}) == 13
    assert got[0]["b"].endswith("…") and len(got[0]["b"].encode()) <= 143
    assert [m["ts"] for m in got] == sorted((m["ts"] for m in got), reverse=True)


# -- MSG_SYNC ----------------------------------------------------------------------


async def test_sync_pages_pending_and_loses_nothing(world):
    _db, dispatch, _rollcall = world
    dispatch.unbind_device(SCOUT, username="aj")  # offline: pushes queue as pending
    ids = {dispatch.send_direct(sender="bob", peer="aj", body=f"{i}: {LONG}")["message"]["id"] for i in range(12)}
    dispatch.bind_device(SCOUT, "aj")

    received, rounds = [], 0
    while True:
        r = await dispatch.handle_rpc(
            _env(SVC_DISPATCH, OP_MSG_SYNC, {"username": "aj", "messages": []})
        )
        rounds += 1
        assert _fits(r) and r.payload["ok"]
        received += [m["id"] for m in r.payload["pending"]]
        if not r.payload["more"]:
            break
        assert rounds < 30
    assert sorted(received) == sorted(ids)  # every one, exactly once
    assert rounds > 1


async def test_sync_for_non_radio_callers_keeps_full_bodies(world):
    db, dispatch, _rollcall = world
    dispatch.bind_device("wifi-aj", "aj")
    dispatch.unbind_device(SCOUT, username="aj")
    dispatch.unbind_device("wifi-aj", username="aj")
    dispatch.send_direct(sender="bob", peer="aj", body=LONG)
    dispatch.bind_device("wifi-aj", "aj")
    r = await dispatch.handle_rpc(
        _env(SVC_DISPATCH, OP_MSG_SYNC, {"username": "aj", "messages": []}, src="wifi-aj")
    )
    assert r.payload["pending"][0]["body"] == LONG.strip()  # stored bodies are stripped


# -- MSG_PUSH ------------------------------------------------------------------------


def test_radio_push_of_a_long_message_fits_one_packet(world):
    _db, dispatch, _rollcall = world
    sent = []
    dispatch.set_radio_push(sent.append)
    dispatch.send_direct(sender="bob", peer="aj", body=LONG)
    assert sent and _fits(sent[0])
    assert sent[0].payload["message"]["body"].endswith("…")
    assert dispatch._outbox[SCOUT][-1]["payload"]["message"]["body"] == LONG.strip()


def test_every_scout_op_is_registered_with_the_gateway(tmp_path: Path):
    """A handler that isn't registered answers unknown_operation over radio
    (MSG_CONVS shipped that way once). Check the real app's gateway."""
    from fastapi.testclient import TestClient

    from server.api.config import Settings
    from server.api.main import create_app

    settings = Settings(
        waypost_data_dir=tmp_path, waypost_sqlite_path=tmp_path / "t.db",
        waypost_transport="mock", waypost_env="test",
    )
    with TestClient(create_app(settings)) as client:
        handlers = client.app.state.gateway._handlers
        for key in [
            ("DISPATCH", "MSG_SEND"), ("DISPATCH", "MSG_LIST"), ("DISPATCH", "MSG_CONVS"),
            ("DISPATCH", "MSG_SYNC"), ("DISPATCH", "MSG_PUSH"),
            ("PROFILE", "PAIR_REDEEM"), ("PROFILE", "WHOAMI"), ("PROFILE", "UNPAIR"),
            ("PROFILE", "ROLL_LIST"), ("FIELDBOOK", "WIKI_SEARCH"), ("FIELDBOOK", "WIKI_GET"),
            ("TRAILHEAD", "TRAIL_GET"), ("CORE", "PING"),
        ]:
            assert key in handlers, key
