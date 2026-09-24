"""Dispatch HTTP + Waylink bridge tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from server.services.dispatch.constants import OP_MSG_ACK, OP_MSG_SEND
from shared.protocol.envelope import SVC_DISPATCH, Envelope, Flags, new_id


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


def test_browser_send_appears_in_conversation(client: TestClient):
    opened = client.post(
        "/api/dispatch/conversations/direct",
        json={"user_a": "aj", "user_b": "bob"},
    )
    assert opened.status_code == 200
    cid = opened.json()["conversation"]["id"]

    sent = client.post(
        "/api/dispatch/messages",
        json={"sender": "aj", "peer": "bob", "body": "Are you near the outpost?", "transport": "wifi"},
    )
    assert sent.status_code == 200
    body = sent.json()
    assert body["created"] is True
    assert body["message"]["body"] == "Are you near the outpost?"
    # bob has no bound Pocket yet → offline queue
    assert body["message"]["delivery_state"] == "QUEUED"

    msgs = client.get(f"/api/dispatch/conversations/{cid}/messages")
    assert msgs.status_code == 200
    texts = [m["body"] for m in msgs.json()["messages"]]
    assert "Are you near the outpost?" in texts


def test_pocket_waylink_send_visible_on_http(client: TestClient):
    client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    env = Envelope(
        src="pocket-bob",
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_SEND,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"sender": "bob", "peer": "aj", "body": "Yeah.", "transport": "lora"},
    )
    r = client.post("/api/waylink/rpc", json=env.to_dict())
    assert r.status_code == 200
    payload = r.json()["payload"]
    assert payload["ok"] is True
    assert payload["transport"] == "lora"

    convs = client.get("/api/dispatch/conversations", params={"username": "aj"})
    assert convs.status_code == 200
    assert len(convs.json()["conversations"]) >= 1
    cid = convs.json()["conversations"][0]["id"]
    msgs = client.get(f"/api/dispatch/conversations/{cid}/messages").json()["messages"]
    assert any(m["body"] == "Yeah." and m["sender"] == "bob" for m in msgs)


def test_browser_send_pushes_to_bound_pocket_outbox(client: TestClient):
    client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    client.post(
        "/api/dispatch/messages",
        json={"sender": "aj", "peer": "bob", "body": "Can you reset it?", "transport": "wifi"},
    )
    out = client.get("/api/waylink/outbox/pocket-bob")
    assert out.status_code == 200
    envelopes = out.json()["envelopes"]
    assert len(envelopes) >= 1
    push = envelopes[0]
    assert push["op"] == "MSG_PUSH"
    assert push["payload"]["message"]["body"] == "Can you reset it?"


def test_message_dedup_by_id(client: TestClient):
    mid = new_id()
    first = client.post(
        "/api/dispatch/messages",
        json={
            "sender": "aj",
            "peer": "bob",
            "body": "Doing it.",
            "message_id": mid,
            "transport": "wifi",
        },
    )
    second = client.post(
        "/api/dispatch/messages",
        json={
            "sender": "aj",
            "peer": "bob",
            "body": "Doing it.",
            "message_id": mid,
            "transport": "lora",
        },
    )
    assert first.json()["created"] is True
    assert second.json()["created"] is False

    cid = first.json()["conversation"]["id"]
    msgs = client.get(f"/api/dispatch/conversations/{cid}/messages").json()["messages"]
    assert sum(1 for m in msgs if m["id"] == mid) == 1


def test_dispatch_page_served(client: TestClient):
    r = client.get("/dispatch.html")
    assert r.status_code == 200
    assert "Dispatch" in r.text


def test_offline_queue_flushes_on_bind(client: TestClient):
    sent = client.post(
        "/api/dispatch/messages",
        json={
            "sender": "aj",
            "peer": "bob",
            "body": "Queued while offline",
            "transport": "wifi",
        },
    )
    assert sent.json()["message"]["delivery_state"] == "QUEUED"
    assert client.get("/api/waylink/outbox/pocket-bob").json()["envelopes"] == []

    sync = client.get("/api/signal").json()["sync"]
    assert sync["pending_dispatch"] >= 1

    bind = client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    assert bind.status_code == 200
    assert bind.json()["flushed"] == 1

    out = client.get("/api/waylink/outbox/pocket-bob").json()["envelopes"]
    assert len(out) == 1
    assert out[0]["payload"]["message"]["body"] == "Queued while offline"

    mid = sent.json()["message"]["id"]
    msgs = client.get(
        f"/api/dispatch/conversations/{sent.json()['conversation']['id']}/messages"
    ).json()["messages"]
    match = next(m for m in msgs if m["id"] == mid)
    # Delivery confirmed when outbox is polled (HTTP Pocket)
    assert match["delivery_state"] == "DELIVERED"
    assert client.get("/api/signal").json()["sync"]["pending_dispatch"] == 0


def test_rebind_reflushes_until_ack(client: TestClient):
    """Pending stays until outbox poll / ACK — second bind can re-offer."""
    sent = client.post(
        "/api/dispatch/messages",
        json={"sender": "aj", "peer": "bob", "body": "Hold for radio", "transport": "lora"},
    )
    mid = sent.json()["message"]["id"]
    client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "radio-bob", "username": "bob"},
    )
    # Do not poll outbox — simulate deaf radio; pending should remain
    assert client.get("/api/signal").json()["sync"]["pending_dispatch"] >= 1

    # Clear in-memory outbox key by acknowledging via RPC
    env = Envelope(
        src="radio-bob",
        dst="station",
        svc=SVC_DISPATCH,
        op=OP_MSG_ACK,
        flags=int(Flags.REQUEST),
        mid=new_id(),
        payload={"message_id": mid, "state": "DELIVERED"},
    )
    r = client.post("/api/waylink/rpc", json=env.to_dict())
    assert r.status_code == 200
    assert client.get("/api/signal").json()["sync"]["pending_dispatch"] == 0



def test_room_messaging(client: TestClient):
    room = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "Crew", "slug": "crew", "members": ["aj", "bob", "sarah"]},
    )
    assert room.status_code == 200
    cid = room.json()["conversation"]["id"]
    assert cid == "room:crew"
    assert set(room.json()["conversation"]["members"]) == {"aj", "bob", "sarah"}

    client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    sent = client.post(
        "/api/dispatch/messages",
        json={
            "sender": "aj",
            "conversation_id": cid,
            "body": "Meet at the outpost",
            "transport": "wifi",
        },
    )
    assert sent.status_code == 200
    # bob online → push; sarah offline → pending → overall QUEUED
    assert sent.json()["message"]["delivery_state"] == "QUEUED"

    out = client.get("/api/waylink/outbox/pocket-bob").json()["envelopes"]
    assert any(
        e["payload"]["message"]["body"] == "Meet at the outpost" for e in out
    )

    bind_sarah = client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-sarah", "username": "sarah"},
    )
    assert bind_sarah.json()["flushed"] == 1
    sarah_out = client.get("/api/waylink/outbox/pocket-sarah").json()["envelopes"]
    assert sarah_out[0]["payload"]["message"]["body"] == "Meet at the outpost"


def test_create_room_from_group_seeds_membership(client: TestClient):
    group = client.post("/api/groups", json={"name": "River Crew"}).json()
    gid = group["id"]
    client.post(f"/api/groups/{gid}/members", json={"username": "bob"})
    client.post(f"/api/groups/{gid}/members", json={"username": "sarah"})

    room = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "River Crew", "group_id": gid},
    )
    assert room.status_code == 200
    members = set(room.json()["conversation"]["members"])
    assert {"aj", "bob", "sarah"} <= members

    # Not live-linked: adding someone to the group afterward doesn't
    # retroactively change the room's membership.
    client.post(f"/api/groups/{gid}/members", json={"username": "carol"})
    conv = client.get(f"/api/dispatch/conversations/{room.json()['conversation']['id']}")
    assert "carol" not in conv.json()["conversation"]["members"]


def test_create_room_requires_members_or_group(client: TestClient):
    r = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "Empty"},
    )
    assert r.status_code == 400


def test_create_room_unknown_group_404s(client: TestClient):
    r = client.post(
        "/api/dispatch/conversations/rooms",
        json={"title": "Ghost", "group_id": "nope"},
    )
    assert r.status_code == 404
