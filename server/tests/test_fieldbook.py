"""Fieldbook tests — progressive path (search → page → section/diff) and
revision-safe editing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from server.services.fieldbook.constants import (
    OP_WIKI_CREATE,
    OP_WIKI_GET,
    OP_WIKI_SEARCH,
    OP_WIKI_UPDATE,
)
from server.services.fieldbook.service import (
    FieldbookService,
    RevisionConflict,
    slugify,
    split_sections,
)
from server.services.fieldbook.store import FieldbookStore
from shared.protocol.envelope import SVC_FIELDBOOK, Envelope, Flags

WELL_BODY = """Intro paragraph about the well.

# Location
Behind the barn, 40 m north of the gate.

# Maintenance
Check the pump seal monthly.
- Grease the bearing
- Log the reading

# Contacts
Ask Bob."""


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        waypost_data_dir=tmp_path,
        waypost_sqlite_path=tmp_path / "test.db",
        waypost_transport="mock",
        waypost_env="test",
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _create(client: TestClient, title="Well maintenance", body=WELL_BODY, **extra):
    r = client.post("/api/fieldbook/pages", json={"title": title, "body": body, **extra})
    assert r.status_code == 201, r.text
    return r.json()


# -- pure helpers ----------------------------------------------------------


def test_slugify_and_sections():
    assert slugify("Well Maintenance!  Notes") == "well-maintenance-notes"
    secs = split_sections(WELL_BODY)
    assert [s["heading"] for s in secs] == ["", "Location", "Maintenance", "Contacts"]
    assert secs[0]["text"].startswith("Intro paragraph")
    assert "\n".join(s["text"] for s in secs) == WELL_BODY


def test_sections_without_preamble_start_at_first_heading():
    secs = split_sections("# A\nx\n# B\ny")
    assert [s["heading"] for s in secs] == ["A", "B"]


# -- HTTP ------------------------------------------------------------------


def test_create_get_list(client: TestClient):
    page = _create(client)
    assert page["slug"] == "well-maintenance"
    assert page["revision"] == 1
    assert page["created_by"] == "aj"

    got = client.get("/api/fieldbook/pages/well-maintenance").json()
    assert got["body"] == WELL_BODY
    assert [s["heading"] for s in got["outline"]] == ["", "Location", "Maintenance", "Contacts"]

    listed = client.get("/api/fieldbook/pages").json()
    assert listed["count"] == 1
    assert listed["pages"][0]["slug"] == "well-maintenance"
    assert "body" not in listed["pages"][0]  # headers only


def test_duplicate_slug_409_and_bad_slug_400(client: TestClient):
    _create(client)
    dup = client.post("/api/fieldbook/pages", json={"title": "Well maintenance", "body": "x"})
    assert dup.status_code == 409
    bad = client.post("/api/fieldbook/pages", json={"title": "T", "slug": "Not Valid!"})
    assert bad.status_code == 400


def test_section_and_outline_fetch(client: TestClient):
    _create(client)
    by_idx = client.get("/api/fieldbook/pages/well-maintenance", params={"section": 2}).json()
    assert by_idx["section"]["heading"] == "Maintenance"
    assert "Grease the bearing" in by_idx["section"]["text"]
    assert "body" not in by_idx

    by_name = client.get(
        "/api/fieldbook/pages/well-maintenance", params={"section": "contacts"}
    ).json()
    assert by_name["section"]["index"] == 3

    missing = client.get("/api/fieldbook/pages/well-maintenance", params={"section": "Nope"})
    assert missing.status_code == 404

    outline = client.get("/api/fieldbook/pages/well-maintenance", params={"outline": True}).json()
    assert "body" not in outline
    assert len(outline["outline"]) == 4


def test_update_bumps_revision_and_keeps_history(client: TestClient):
    _create(client)
    r = client.put(
        "/api/fieldbook/pages/well-maintenance",
        json={"base_revision": 1, "body": WELL_BODY + "\nNew line.", "summary": "add note"},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == 2
    assert r.json()["updated_by"] == "aj"

    hist = client.get("/api/fieldbook/pages/well-maintenance/history").json()["revisions"]
    assert [h["revision"] for h in hist] == [2, 1]
    assert hist[0]["summary"] == "add note"
    assert hist[1]["summary"] == "created"

    rev1 = client.get("/api/fieldbook/pages/well-maintenance/revisions/1").json()
    assert rev1["body"] == WELL_BODY


def test_stale_base_revision_conflicts_without_overwriting(client: TestClient):
    _create(client)
    first = client.put(
        "/api/fieldbook/pages/well-maintenance",
        json={"base_revision": 1, "body": WELL_BODY + "\nBob's line."},
    )
    assert first.status_code == 200

    # Second editor still on revision 1 — must not clobber Bob's save.
    second = client.put(
        "/api/fieldbook/pages/well-maintenance",
        json={"base_revision": 1, "body": WELL_BODY + "\nCarol's line."},
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["error"] == "revision_conflict"
    assert detail["current"]["revision"] == 2
    assert detail["current"]["body"].endswith("Bob's line.")

    page = client.get("/api/fieldbook/pages/well-maintenance").json()
    assert page["revision"] == 2
    assert "Carol" not in page["body"]


def test_section_edit_replaces_only_that_section(client: TestClient):
    _create(client)
    r = client.put(
        "/api/fieldbook/pages/well-maintenance",
        json={
            "base_revision": 1,
            "section": "Contacts",
            "section_text": "# Contacts\nAsk Carol, not Bob.",
        },
    )
    assert r.status_code == 200
    body = r.json()["body"]
    assert body.endswith("# Contacts\nAsk Carol, not Bob.")
    assert "Behind the barn" in body  # other sections untouched
    assert "Grease the bearing" in body


def test_diff_and_since(client: TestClient):
    _create(client, body="# A\none\n# B\ntwo")
    client.put(
        "/api/fieldbook/pages/well-maintenance",
        json={"base_revision": 1, "body": "# A\none\n# B\nTWO changed"},
    )

    same = client.get("/api/fieldbook/pages/well-maintenance", params={"since": 2}).json()
    assert same == {"slug": "well-maintenance", "revision": 2, "unchanged": True}

    d = client.get("/api/fieldbook/pages/well-maintenance", params={"since": 1}).json()
    assert d["from_revision"] == 1 and d["to_revision"] == 2
    assert "-two" in d["diff"] and "+TWO changed" in d["diff"]
    assert "body" not in d

    explicit = client.get(
        "/api/fieldbook/pages/well-maintenance/diff", params={"from": 1, "to": 2}
    ).json()
    assert explicit["diff"] == d["diff"]


def test_search_returns_compact_hits(client: TestClient):
    _create(client)
    _create(client, title="Radio checklist", body="Charge the Pocket. Check the antenna.")

    hits = client.get("/api/fieldbook/search", params={"q": "antenna"}).json()["results"]
    assert len(hits) == 1
    assert hits[0]["slug"] == "radio-checklist"
    assert hits[0]["match"] == "body"
    assert "antenna" in hits[0]["snippet"].lower()
    assert "body" not in hits[0]

    title_hits = client.get("/api/fieldbook/search", params={"q": "well"}).json()["results"]
    assert title_hits[0]["match"] == "title"

    assert client.get("/api/fieldbook/search", params={"q": ""}).json()["results"] == []


def test_unknown_page_404s(client: TestClient):
    assert client.get("/api/fieldbook/pages/nope").status_code == 404
    assert client.get("/api/fieldbook/pages/nope/history").status_code == 404
    r = client.put("/api/fieldbook/pages/nope", json={"base_revision": 1, "body": "x"})
    assert r.status_code == 404


def test_fieldbook_page_and_dashboard_activity(client: TestClient):
    r = client.get("/fieldbook.html")
    assert r.status_code == 200
    assert "fieldbook.js" in r.text

    _create(client)
    dash = client.get("/api/dashboard", params={"username": "aj"}).json()
    fb = [a for a in dash["activity"] if a["service"] == "Fieldbook"]
    assert fb and "Well maintenance" in fb[0]["text"]
    assert fb[0]["href"].endswith("#well-maintenance")


# -- Waylink (radio path) --------------------------------------------------


def _memory_service(bindings: dict) -> FieldbookService:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return FieldbookService(FieldbookStore(conn), get_binding=lambda n: bindings.get(n))


def _env(src: str, op: str, payload: dict) -> Envelope:
    return Envelope(
        src=src, dst="station", svc=SVC_FIELDBOOK, op=op, flags=int(Flags.REQUEST), payload=payload
    )


def test_radio_progressive_path_search_outline_section_diff():
    svc = _memory_service({"pocket-carol": {"username": "carol"}})
    svc.create_page(author="aj", title="Well maintenance", body=WELL_BODY)

    hits = svc.handle_rpc(_env("pocket-x", OP_WIKI_SEARCH, {"q": "pump"})).payload["results"]
    assert hits[0]["slug"] == "well-maintenance" and "body" not in hits[0]

    outline = svc.handle_rpc(
        _env("pocket-x", OP_WIKI_GET, {"slug": "well-maintenance", "outline": True})
    ).payload
    assert "body" not in outline
    assert [s["heading"] for s in outline["outline"]][1:] == ["Location", "Maintenance", "Contacts"]

    sec = svc.handle_rpc(
        _env("pocket-x", OP_WIKI_GET, {"slug": "well-maintenance", "section": "Maintenance"})
    ).payload
    assert sec["section"]["heading"] == "Maintenance" and "body" not in sec

    # Pocket holds rev 1; nothing changed → tiny reply.
    same = svc.handle_rpc(_env("pocket-x", OP_WIKI_GET, {"slug": "well-maintenance", "since": 1}))
    assert same.payload["unchanged"] is True

    svc.handle_rpc(
        _env(
            "pocket-carol",
            OP_WIKI_UPDATE,
            {
                "slug": "well-maintenance",
                "base_revision": 1,
                "section": "Contacts",
                "section_text": "# Contacts\nAsk Carol.",
            },
        )
    )
    delta = svc.handle_rpc(_env("pocket-x", OP_WIKI_GET, {"slug": "well-maintenance", "since": 1}))
    assert delta.payload["to_revision"] == 2
    assert "+Ask Carol." in delta.payload["diff"] and "body" not in delta.payload


def test_radio_writes_require_bound_device_and_use_bound_author():
    svc = _memory_service({"pocket-carol": {"username": "carol"}})

    denied = svc.handle_rpc(
        _env("pocket-unknown", OP_WIKI_CREATE, {"title": "T", "body": "b", "author": "aj"})
    )
    assert denied.payload["error"] == "unauthorized_device"
    assert svc.count_pages() == 0

    ok = svc.handle_rpc(_env("pocket-carol", OP_WIKI_CREATE, {"title": "Trail notes", "body": "b"}))
    assert not (ok.flags & int(Flags.ERROR))
    assert ok.payload["page"]["created_by"] == "carol"
    assert "body" not in ok.payload["page"]  # ack stays small

    denied_update = svc.handle_rpc(
        _env("pocket-unknown", OP_WIKI_UPDATE, {"slug": "trail-notes", "base_revision": 1, "body": "x"})
    )
    assert denied_update.payload["error"] == "unauthorized_device"
    assert svc.get_page("trail-notes")["revision"] == 1


def test_radio_conflict_returns_outline_not_body():
    svc = _memory_service({"pocket-carol": {"username": "carol"}})
    svc.create_page(author="aj", title="Well maintenance", body=WELL_BODY)
    svc.update_page("well-maintenance", author="aj", base_revision=1, body=WELL_BODY + "\nmore")

    stale = svc.handle_rpc(
        _env(
            "pocket-carol",
            OP_WIKI_UPDATE,
            {"slug": "well-maintenance", "base_revision": 1, "body": "clobber"},
        )
    )
    assert stale.flags & int(Flags.ERROR)
    assert stale.payload["error"] == "revision_conflict"
    assert stale.payload["current_revision"] == 2
    assert "outline" in stale.payload and "body" not in stale.payload
    assert svc.get_page("well-maintenance")["body"].endswith("more")


def test_service_conflict_exception_carries_current():
    svc = _memory_service({})
    svc.create_page(author="aj", title="P", body="one")
    svc.update_page("p", author="aj", base_revision=1, body="two")
    with pytest.raises(RevisionConflict) as exc:
        svc.update_page("p", author="bob", base_revision=1, body="three")
    assert exc.value.current["revision"] == 2
    assert exc.value.current["body"] == "two"


def test_noop_save_does_not_create_revision():
    svc = _memory_service({})
    svc.create_page(author="aj", title="P", body="same")
    page = svc.update_page("p", author="aj", base_revision=1, body="same")
    assert page["revision"] == 1
    assert len(svc.history("p")) == 1
