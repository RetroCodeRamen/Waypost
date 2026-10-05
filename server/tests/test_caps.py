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
