"""Trailhead (small web) + radio-sized Fieldbook reads.

The radio tests guard one hard limit: a Scout over LoRa only receives what
fits in one encrypted Reticulum packet (shared/protocol/radio.py's
RADIO_MDU), so every reply shape a Scout requests is encoded and measured.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.config import Settings
from server.api.main import create_app
from server.services.fieldbook.constants import OP_WIKI_GET, OP_WIKI_SEARCH
from server.services.fieldbook.service import FieldbookService
from server.services.fieldbook.store import FieldbookStore
from server.services.trailhead.constants import OP_TRAIL_GET
from server.services.trailhead.service import TrailheadService
from server.services.trailhead.store import TrailheadStore
from shared.protocol.envelope import (
    SVC_FIELDBOOK,
    SVC_TRAILHEAD,
    Envelope,
    Flags,
    encode_cbor,
)
from shared.protocol.radio import RADIO_MDU, chunk_utf8

# Worst case for the reply's dst (= request src): a 32-hex node id.
LONG_SRC = "e75a4c2818b4cd84b800d98827a11ed9"


def _env(svc: str, op: str, payload: dict, src: str = LONG_SRC) -> Envelope:
    return Envelope(
        src=src, dst="station", svc=svc, op=op, flags=int(Flags.REQUEST), payload=payload
    )


def _fits(env: Envelope) -> bool:
    return len(encode_cbor(env)) <= RADIO_MDU


def _trailhead() -> TrailheadService:
    conn = sqlite3.connect(":memory:")
    svc = TrailheadService(TrailheadStore(conn))
    svc.seed_defaults()
    return svc


def _read_all(rpc, make_payload) -> tuple[str, list[Envelope]]:
    """Follow offsets the way a Scout does until `total` bytes are read."""
    out = b""
    replies = []
    offset = 0
    while True:
        reply = rpc(make_payload(offset))
        replies.append(reply)
        p = reply.payload
        assert p["offset"] == offset
        out += p["text"].encode("utf-8")
        offset += len(p["text"].encode("utf-8"))
        if offset >= p["total"]:
            return out.decode("utf-8"), replies
        assert p["text"], "no progress"


# -- chunk helper -------------------------------------------------------------


def test_chunk_utf8_never_splits_a_character():
    text = "ab" + "é" * 50 + "🌲" * 20
    raw = text.encode("utf-8")
    for limit in range(4, 40):
        offset, rebuilt = 0, b""
        while offset < len(raw):
            piece, total = chunk_utf8(text, offset, limit)
            assert total == len(raw)
            b = piece.encode("utf-8")
            assert b and len(b) <= limit
            rebuilt += b
            offset += len(b)
        assert rebuilt == raw


def test_chunk_utf8_offset_past_end_is_empty():
    piece, total = chunk_utf8("hello", 99, 10)
    assert piece == "" and total == 5


# -- Trailhead --------------------------------------------------------------


def test_seed_pages_exist_once():
    svc = _trailhead()
    paths = [p["path"] for p in svc.list_pages()]
    assert {"home", "getting-started", "camp-info", "survival", "commons-feed"} <= set(
        paths
    )
    svc.seed_defaults()
    assert len(svc.list_pages()) == len(paths)


def test_trail_get_reads_whole_page_in_radio_sized_chunks():
    svc = _trailhead()
    body = "# Long page\n" + ("Water is at the north tap. Ünïcödé ok 🌲. " * 40) + "\n=> home Back"
    svc.save_page("guide/water", title="Water at the north tap and how to keep it clean for everyone here", body=body, author="aj")

    text, replies = _read_all(
        svc.handle_rpc,
        lambda off: _env(SVC_TRAILHEAD, OP_TRAIL_GET, {"path": "guide/water", "offset": off, "limit": 160}),
    )
    assert text == body
    assert len(replies) > 5
    assert all(_fits(r) for r in replies)
    assert replies[0].payload["title"].startswith("Water")
    assert "title" not in replies[1].payload


def test_trail_get_defaults_to_home_and_reports_missing():
    svc = _trailhead()
    home = svc.handle_rpc(_env(SVC_TRAILHEAD, OP_TRAIL_GET, {"limit": 160}))
    assert home.payload["path"] == "home" and home.payload["total"] > 0
    missing = svc.handle_rpc(_env(SVC_TRAILHEAD, OP_TRAIL_GET, {"path": "nope"}))
    assert missing.flags & Flags.ERROR and missing.payload["error"] == "not_found"


def test_trail_get_oversized_limit_is_clamped_to_one_packet():
    svc = _trailhead()
    svc.save_page("big", title="Big", body="x" * 5000, author="aj")
    reply = svc.handle_rpc(_env(SVC_TRAILHEAD, OP_TRAIL_GET, {"path": "big", "limit": 4000}))
    assert _fits(reply) and len(reply.payload["text"]) > 100


def test_save_page_validates_path():
    svc = _trailhead()
    for bad in ("", "Has Space", "../etc", "x" * 65):
        with pytest.raises(ValueError):
            svc.save_page(bad, title="t", body="b", author="aj")
    assert svc.save_page("/Camp/Rules/", title="Rules", body="b", author="aj")["path"] == "camp/rules"


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


def test_http_crud_and_portal_page(client: TestClient):
    pages = client.get("/api/trailhead/pages").json()["pages"]
    assert any(p["path"] == "home" for p in pages)

    r = client.put("/api/trailhead/pages/camp/rules", json={"title": "Rules", "body": "# Rules\nBe kind."})
    assert r.status_code == 200 and r.json()["path"] == "camp/rules"
    assert client.get("/api/trailhead/pages/camp/rules").json()["body"] == "# Rules\nBe kind."

    assert client.put("/api/trailhead/pages/Bad Path", json={"title": "x", "body": ""}).status_code == 400
    assert client.delete("/api/trailhead/pages/camp/rules").status_code == 200
    assert client.get("/api/trailhead/pages/camp/rules").status_code == 404

    assert client.get("/trailhead.html").status_code == 200


# -- Fieldbook radio-sized reads --------------------------------------------

LONG_SECTION = "# Pump\n" + ("Prime the pump, then open valve B slowly — señal ✓. " * 60)


def _fieldbook() -> FieldbookService:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    svc = FieldbookService(FieldbookStore(conn))
    for i in range(12):
        svc.create_page(
            author="aj",
            title=f"Pump maintenance volume {i} with a deliberately long title",
            slug=f"pump-maintenance-volume-{i}-with-a-long-slug-for-sizing",
            body=f"Intro {i}\n\n" + "".join(f"# Heading number {j} about pumps\nText.\n" for j in range(25)),
        )
    svc.create_page(author="aj", title="Well", slug="well", body="Intro\n\n" + LONG_SECTION)
    return svc


def test_compact_search_pages_through_every_hit_in_one_packet_each():
    svc = _fieldbook()
    seen, offset = [], 0
    while True:
        reply = svc.handle_rpc(
            _env(SVC_FIELDBOOK, OP_WIKI_SEARCH, {"q": "pump", "compact": True, "offset": offset})
        )
        assert _fits(reply)
        p = reply.payload
        assert p["results"] and all(set(r) == {"slug", "title"} for r in p["results"])
        seen += [r["slug"] for r in p["results"]]
        offset += len(p["results"])
        if not p["more"]:
            break
    # 12 pump pages + "well", whose body mentions priming the pump.
    assert len(seen) == len(set(seen)) == 13


def test_outline_paging_fits_and_covers_all_sections():
    svc = _fieldbook()
    slug = "pump-maintenance-volume-0-with-a-long-slug-for-sizing"
    headings, offset = [], 0
    while True:
        reply = svc.handle_rpc(
            _env(SVC_FIELDBOOK, OP_WIKI_GET, {"slug": slug, "outline": True, "offset": offset, "limit": 8})
        )
        assert _fits(reply)
        part = reply.payload["outline"]
        headings += [o["heading"] for o in part]
        offset += len(part)
        if not reply.payload["more"]:
            break
    assert len(headings) == 26  # intro + 25 headings


def test_section_chunks_rebuild_the_section_exactly():
    svc = _fieldbook()
    text, replies = _read_all(
        svc.handle_rpc,
        lambda off: _env(
            SVC_FIELDBOOK, OP_WIKI_GET, {"slug": "well", "section": 1, "offset": off, "limit": 160}
        ),
    )
    assert text == LONG_SECTION
    assert all(_fits(r) for r in replies)


def test_full_shapes_unchanged_without_limit():
    svc = _fieldbook()
    sec = svc.handle_rpc(_env(SVC_FIELDBOOK, OP_WIKI_GET, {"slug": "well", "section": 1})).payload
    assert sec["section"]["text"] == LONG_SECTION
    hits = svc.handle_rpc(_env(SVC_FIELDBOOK, OP_WIKI_SEARCH, {"q": "well"})).payload["results"]
    assert "snippet" in hits[0]
