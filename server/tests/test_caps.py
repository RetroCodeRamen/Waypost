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


def test_network_block_is_added_replaced_and_removed(tmp_path):
    from RNS.vendor.configobj import ConfigObj  # what Reticulum parses it with

    from server.transports.reticulum import RNodeRadio, _default_config, apply_network, parse_upstreams

    _default_config(tmp_path, interface="rnode", rnode=RNodeRadio(port="/dev/waypost-lora"))
    cfg = tmp_path / "config"
    apply_network(cfg, upstreams=parse_upstreams("hub.example.org:4242, 10.0.0.5:4965, nonsense"),
                  wifi_device="wlan0")
    conf = ConfigObj(str(cfg))["interfaces"]
    assert conf["WAYPOST Wi-Fi"]["devices"] == "wlan0" and conf["WAYPOST Wi-Fi"]["mode"] == "gateway"
    assert conf["WAYPOST Wi-Fi TCP"]["listen_ip"] == "10.42.0.1"
    assert conf["Uplink 1"]["target_host"] == "hub.example.org" and "Uplink 2" in conf
    assert conf["RNode LoRa"]["mode"] == "gateway"

    apply_network(cfg, upstreams=parse_upstreams("10.0.0.5:4965"), wifi_device="wlan0")
    conf = ConfigObj(str(cfg))["interfaces"]
    assert "Uplink 2" not in conf and conf["Uplink 1"]["target_host"] == "10.0.0.5"
    assert cfg.read_text().count("mode = gateway") == 3  # radio not doubled

    apply_network(cfg, upstreams=[])
    conf = ConfigObj(str(cfg))["interfaces"]
    assert set(conf) == {"RNode LoRa"}


# -- reply routes from announces (guess_destination) --------------------------------


def test_guess_destination_from_announces(monkeypatch):
    import RNS

    from server.transports.reticulum import APP_NAME, ASPECT, ReticulumTransport

    def waylink_dest(ident):
        return bytes(RNS.Destination.hash(ident, APP_NAME, ASPECT))

    known = {}
    scout = RNS.Identity()
    d = waylink_dest(scout)
    known[d] = [0, b"", scout.get_public_key(), b"", 0]
    other = RNS.Identity()  # some other app's destination: never matched
    known[bytes(RNS.Destination.hash(other, "nomadnetwork", "node"))] = [0, b"", other.get_public_key(), b"", 0]
    monkeypatch.setattr(RNS.Identity, "known_destinations", known)

    t = ReticulumTransport(interface="tcp")
    assert t.guess_destination("pocket-1-" + d.hex()[:4]) == d.hex()
    assert t.resolve_destination("pocket-1-" + d.hex()[:4]) == d.hex()  # learned
    assert t.guess_destination("pocket-1-zzzz") is None
    assert t.guess_destination("station") is None

    # A forged entry (same prefix, but the hash isn't its key's Waylink
    # destination) is ignored, so it can't make the match ambiguous or win.
    forged = RNS.Identity()
    known[d[:2] + waylink_dest(forged)[2:]] = [0, b"", forged.get_public_key(), b"", 0]
    assert ReticulumTransport(interface="tcp").guess_destination("pocket-1-" + d.hex()[:4]) == d.hex()


# -- "who's there?" answers -----------------------------------------------------------


def test_station_answers_whos_there_once(monkeypatch):
    import time

    from server.transports import reticulum as R

    t = R.ReticulumTransport(interface="tcp")
    announced = []

    class Dest:
        def announce(self, app_data=None):
            announced.append(app_data)

    t._destination = Dest()
    t._running = True
    monkeypatch.setattr(R.random, "random", lambda: 0.0)  # answer after the minimum 0.3 s

    t._on_nearby_probe(b"something else", None)  # not a probe
    t._on_nearby_probe(R.NEARBY_PROBE, None)
    t._on_nearby_probe(R.NEARBY_PROBE + b"again", None)  # while one answer is pending
    time.sleep(0.6)
    assert len(announced) == 1 and K.split(announced[0])[1].role == K.ROLE_STATION
    t._on_nearby_probe(R.NEARBY_PROBE, None)  # within 30 s of answering
    time.sleep(0.6)
    assert len(announced) == 1
