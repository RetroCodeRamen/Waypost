"""Capability records in announces (roadmap D6, shared/protocol/caps.py)."""

from __future__ import annotations

import asyncio

from shared.protocol import caps as K
from server.transports.reticulum import AUTO_CLAIM_MARKER, ReticulumTransport


def test_record_round_trips_and_is_small():
    c = K.Caps(role=K.ROLE_OUTPOST, services=K.SVC_DISPATCH | K.SVC_SYNC | K.SVC_WIFI_PAGE,
               station=K.ST_DIRECT, name="North Gate Ranger Cabin xx")  # longer than the 24 kept
    data = K.app_data(b"WPOST-OUTPOST:outpost-1-0e21", c)
    marker, back = K.split(data)
    assert marker == b"WPOST-OUTPOST:outpost-1-0e21"
    assert back == K.Caps(role=K.ROLE_OUTPOST, services=c.services, station=K.ST_DIRECT, name=c.name[:24])
    assert len(K.encode(c)) <= K.MAX_RECORD
    assert len(K.encode(K.Caps(role=K.ROLE_STATION, services=K.STATION_SERVICES, station=K.ST_SELF))) <= K.MAX_RECORD


def test_old_announces_still_parse():
    assert K.split(b"WPOST-CLAIM:outpost-1-0e21") == (b"WPOST-CLAIM:outpost-1-0e21", None)
    assert K.split(None) == (b"", None)
    assert K.split(b"WPOST-OUTPOST:x\x00\xff\xfe") == (b"WPOST-OUTPOST:x", None)  # garbage record ignored


def test_station_announces_itself():
    _, c = K.split(ReticulumTransport.announce_data())
    assert c.role == K.ROLE_STATION and c.station == K.ST_SELF and c.services & K.SVC_SYNC


async def test_auto_claim_reads_the_marker_not_the_record():
    t = ReticulumTransport(interface="tcp")
    claimed = []
    t.on_unclaimed_outpost_announce = lambda node, dest, name: claimed.append((node, dest, name))
    t._loop = asyncio.get_running_loop()
    data = K.app_data(AUTO_CLAIM_MARKER + b"outpost-1-0e21|North Gate",
                      K.Caps(role=K.ROLE_OUTPOST, services=K.SVC_SYNC, name="North Gate"))
    t._on_announce(bytes(range(16)), None, data)
    await asyncio.sleep(0)
    assert claimed == [("outpost-1-0e21", bytes(range(16)).hex(), "North Gate")]


# -- Reticulum uplinks (WAYPOST_RNS_UPSTREAM) ---------------------------------------


def test_uplinks_are_added_replaced_and_removed(tmp_path):
    from server.transports.reticulum import RNodeRadio, _default_config, apply_uplinks, parse_upstreams

    _default_config(tmp_path, interface="rnode", rnode=RNodeRadio(port="/dev/waypost-lora"))
    cfg = tmp_path / "config"
    apply_uplinks(cfg, parse_upstreams("hub.example.org:4242, 10.0.0.5:4965, nonsense"))
    text = cfg.read_text()
    assert text.count("type = TCPClientInterface") == 2 and "target_host = hub.example.org" in text
    assert "mode = gateway" in text
    apply_uplinks(cfg, parse_upstreams("10.0.0.5:4965"))
    text = cfg.read_text()
    assert text.count("type = TCPClientInterface") == 1 and "hub.example.org" not in text
    apply_uplinks(cfg, [])
    assert "TCPClientInterface" not in cfg.read_text() and "type = RNodeInterface" in cfg.read_text()

    from RNS.vendor.configobj import ConfigObj  # what Reticulum parses it with

    conf = ConfigObj(str(cfg))
    assert "RNode LoRa" in conf["interfaces"]
