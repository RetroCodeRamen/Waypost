"""Postbox tests — progressive retrieval + Waylink MAIL_*."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from server.services.mail.constants import OP_MAIL_GET, OP_MAIL_LIST, OP_MAIL_STATUS
from shared.protocol.envelope import SVC_MAIL, Envelope, Flags, new_id


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


def test_send_and_list_headers(client: TestClient):
    sent = client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Generator",
            "body": "Fuel arrived at the shed.",
        },
    )
    assert sent.status_code == 200
    assert sent.json()["delivered_to"] == "bob"

    st = client.get("/api/postbox/status", params={"mailbox": "bob"})
    assert st.json()["unread"] == 1

    listing = client.get("/api/postbox/messages", params={"mailbox": "bob"})
    msgs = listing.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["subject"] == "Generator"
    assert "body" not in msgs[0]


def test_progressive_get_marks_read(client: TestClient):
    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob",
            "subject": "Weather",
            "body": "Storm after 9.",
        },
    )
    headers = client.get("/api/postbox/messages", params={"mailbox": "bob"}).json()[
        "messages"
    ]
    n = headers[0]["local_id"]
    got = client.get(
        f"/api/postbox/messages/{n}", params={"mailbox": "bob"}
    )
    assert got.status_code == 200
    assert got.json()["body"] == "Storm after 9."
    assert client.get("/api/postbox/status", params={"mailbox": "bob"}).json()[
        "unread"
    ] == 0


def test_attachment_wifi_only_metadata(client: TestClient):
    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Manual",
            "body": "See attached.",
            "attachment_name": "generator-manual.pdf",
            "attachment_size": 2400000,
        },
    )
    n = client.get("/api/postbox/messages", params={"mailbox": "bob"}).json()[
        "messages"
    ][0]["local_id"]
    msg = client.get(
        f"/api/postbox/messages/{n}", params={"mailbox": "bob"}
    ).json()
    assert msg["has_attachment"] is True
    assert msg["attachment_wifi_only"] is True


def test_waylink_mail_status_list_get(client: TestClient):
    client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Food Inventory",
            "body": "Pantry counts updated.",
        },
    )
    # Notify should be in outbox
    out = client.get("/api/waylink/outbox/pocket-bob").json()["envelopes"]
    assert any(e["op"] == "MAIL_NOTIFY" for e in out)

    status = client.post(
        "/api/waylink/rpc",
        json=Envelope(
            src="pocket-bob",
            dst="station",
            svc=SVC_MAIL,
            op=OP_MAIL_STATUS,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={},  # mailbox from binding
        ).to_dict(),
    )
    assert status.json()["payload"]["unread"] == 1

    listing = client.post(
        "/api/waylink/rpc",
        json=Envelope(
            src="pocket-bob",
            dst="station",
            svc=SVC_MAIL,
            op=OP_MAIL_LIST,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={"limit": 5},
        ).to_dict(),
    )
    messages = listing.json()["payload"]["messages"]
    assert messages[0]["subj"] == "Food Inventory"
    assert "body" not in messages[0]

    got = client.post(
        "/api/waylink/rpc",
        json=Envelope(
            src="pocket-bob",
            dst="station",
            svc=SVC_MAIL,
            op=OP_MAIL_GET,
            flags=int(Flags.REQUEST),
            mid=new_id(),
            payload={"n": messages[0]["n"]},
        ).to_dict(),
    )
    assert got.json()["payload"]["body"] == "Pantry counts updated."


def test_reply(client: TestClient):
    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Tonight",
            "body": "Meeting?",
        },
    )
    n = client.get("/api/postbox/messages", params={"mailbox": "bob"}).json()[
        "messages"
    ][0]["local_id"]
    reply = client.post(
        "/api/postbox/reply",
        json={"from_user": "bob", "local_id": n, "body": "Yes, 19:00."},
    )
    assert reply.status_code == 200
    aj_inbox = client.get("/api/postbox/messages", params={"mailbox": "aj"}).json()[
        "messages"
    ]
    assert any(m["subject"].startswith("Re:") for m in aj_inbox)


def test_outbox_queue_and_flush(client: TestClient):
    queued = client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Hold this",
            "body": "Not sent yet.",
            "queue_only": True,
        },
    )
    assert queued.status_code == 200
    assert queued.json()["queued"] is True
    assert client.get("/api/postbox/status", params={"mailbox": "aj"}).json()[
        "outbox"
    ] == 1
    assert (
        client.get(
            "/api/postbox/messages",
            params={"mailbox": "bob", "folder": "INBOX"},
        ).json()["messages"]
        == []
    )
    outbox = client.get(
        "/api/postbox/messages",
        params={"mailbox": "aj", "folder": "OUTBOX"},
    ).json()["messages"]
    assert len(outbox) == 1
    assert outbox[0]["subject"] == "Hold this"

    flushed = client.post(
        "/api/postbox/outbox/flush",
        json={"mailbox": "aj"},
    )
    assert flushed.status_code == 200
    assert flushed.json()["count"] == 1
    assert client.get("/api/postbox/status", params={"mailbox": "aj"}).json()[
        "outbox"
    ] == 0
    bob_inbox = client.get(
        "/api/postbox/messages", params={"mailbox": "bob"}
    ).json()["messages"]
    assert any(m["subject"] == "Hold this" for m in bob_inbox)
    sent = client.get(
        "/api/postbox/messages",
        params={"mailbox": "aj", "folder": "SENT"},
    ).json()["messages"]
    assert any(m["subject"] == "Hold this" for m in sent)


def test_mail_notify_persists_until_bind(client: TestClient):
    client.post(
        "/api/postbox/messages",
        json={
            "from_user": "aj",
            "to": "bob@waypost",
            "subject": "Offline notify",
            "body": "See you later.",
        },
    )
    # No pocket bound yet — notify stored under user:bob
    assert client.get("/api/waylink/outbox/pocket-bob").json()["envelopes"] == []

    bind = client.post(
        "/api/dispatch/devices/bind",
        json={"node_id": "pocket-bob", "username": "bob"},
    )
    assert bind.json().get("mail_notifies_flushed", 0) >= 1
    out = client.get("/api/waylink/outbox/pocket-bob").json()["envelopes"]
    assert any(e["op"] == "MAIL_NOTIFY" for e in out)


def test_postbox_page(client: TestClient):
    assert client.get("/postbox.html").status_code == 200
