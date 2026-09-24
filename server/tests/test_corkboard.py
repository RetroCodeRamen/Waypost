"""Corkboard — Station-side logic (M6, sim-only).

Proves the real Station-side contract without needing OutpostNode's own
sync method (which doesn't exist yet — see AGENT_HANDOFF.md): a BOARD_SYNC
envelope is constructed directly and posted to /api/waylink/rpc, the same
mock-transport-less path server/tests/test_dispatch.py already uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from shared.protocol.envelope import SVC_CORKBOARD, Envelope, Flags, new_id
from server.services.corkboard.constants import OP_BOARD_SYNC


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="test",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _sync(client: TestClient, *, outpost_id: str, notes: list, display_name=None):
    env = Envelope(
        src=outpost_id,
        dst="station",
        svc=SVC_CORKBOARD,
        op=OP_BOARD_SYNC,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"display_name": display_name, "notes": notes},
    )
    r = client.post("/api/waylink/rpc", json=env.to_dict())
    assert r.status_code == 200
    return r.json()


def test_board_sync_registers_outpost_and_ingests_notes(client: TestClient):
    reply = _sync(
        client,
        outpost_id="outpost-1",
        display_name="Ridge Trailhead",
        notes=[{"id": new_id(), "body": "Bear spotted near creek", "signature": "-Jamie"}],
    )
    assert reply["payload"]["ok"] is True
    assert reply["payload"]["ingested"] == 1

    outposts = client.get("/api/corkboard/outposts").json()["outposts"]
    assert any(
        o["node_id"] == "outpost-1" and o["display_name"] == "Ridge Trailhead"
        for o in outposts
    )

    notes = client.get("/api/corkboard/outposts/outpost-1/notes").json()["notes"]
    assert any(n["body"] == "Bear spotted near creek" and n["signature"] == "-Jamie" for n in notes)


def test_resync_same_notes_dedups(client: TestClient):
    note_id = new_id()
    _sync(client, outpost_id="outpost-1", notes=[{"id": note_id, "body": "River flooded"}])
    reply2 = _sync(client, outpost_id="outpost-1", notes=[{"id": note_id, "body": "River flooded"}])
    assert reply2["payload"]["ingested"] == 0

    notes = client.get("/api/corkboard/outposts/outpost-1/notes").json()["notes"]
    assert sum(1 for n in notes if n["body"] == "River flooded") == 1


def test_notes_scoped_per_outpost_never_merged(client: TestClient):
    _sync(client, outpost_id="outpost-1", notes=[{"id": new_id(), "body": "Dam broke near A"}])
    _sync(client, outpost_id="outpost-2", notes=[{"id": new_id(), "body": "Trail closed near B"}])

    notes_1 = [n["body"] for n in client.get("/api/corkboard/outposts/outpost-1/notes").json()["notes"]]
    notes_2 = [n["body"] for n in client.get("/api/corkboard/outposts/outpost-2/notes").json()["notes"]]
    assert notes_1 == ["Dam broke near A"]
    assert notes_2 == ["Trail closed near B"]


def test_post_note_queues_and_piggybacks_on_next_sync(client: TestClient):
    _sync(client, outpost_id="outpost-1", notes=[])  # register it first

    posted = client.post(
        "/api/corkboard/outposts/outpost-1/notes",
        json={"body": "Resupply arriving Friday", "signature": "Station"},
    )
    assert posted.status_code == 201

    reply = _sync(client, outpost_id="outpost-1", notes=[])
    pending = reply["payload"]["pending"]
    assert any(p["body"] == "Resupply arriving Friday" for p in pending)

    # Piggybacked once -> gone from the outbox on the next sync.
    reply2 = _sync(client, outpost_id="outpost-1", notes=[])
    assert reply2["payload"]["pending"] == []


def test_post_note_rejects_empty_body(client: TestClient):
    _sync(client, outpost_id="outpost-1", notes=[])
    r = client.post(
        "/api/corkboard/outposts/outpost-1/notes",
        json={"body": "   ", "signature": None},
    )
    assert r.status_code == 400


def test_corkboard_page_served(client: TestClient):
    r = client.get("/corkboard.html")
    assert r.status_code == 200
    assert "Corkboard" in r.text
