"""Capability records in Reticulum announces (roadmap D6,
docs/network-model.md §6).

Every Waypost node says what it can do, not where it sits in a hierarchy.
It does this in its announce's ``app_data``:

    <marker text> NUL <CBOR capability record>

The marker text is what older code reads (``WPOST-CLAIM:<id>``,
``WPOST-OUTPOST:<id>``; empty for Station and Scouts). Everything before the
NUL keeps its old meaning. The record:

    r   role bits          ROLE_*
    s   services bitmap    SVC_*
    st  Station reach      ST_*
    n   short name         Outposts only. Scouts don't put a name on the
                           air: an announce is public, and a person's name in
                           it would tell anyone listening who is around.

Kept small (an announce is one packet with a key and signature already in
it): MAX_RECORD bytes, tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ROLE_STATION = 1
ROLE_OUTPOST = 2
ROLE_SCOUT = 4

SVC_DISPATCH = 1 << 0
SVC_POSTBOX = 1 << 1
SVC_NOTICEBOARD = 1 << 2
SVC_BEACON = 1 << 3
SVC_FIELDBOOK = 1 << 4
SVC_COMMONS = 1 << 5
SVC_LOCKER = 1 << 6
SVC_ROLLCALL = 1 << 7
SVC_CORKBOARD = 1 << 8
SVC_TRAILHEAD = 1 << 9
SVC_SIGNAL = 1 << 10
SVC_SYNC = 1 << 11      # answers peer sync (SYNC HELLO/SUM/WANT/PUT)
SVC_WIFI_PAGE = 1 << 12  # people can sign in on its Wi-Fi (Outpost /msg)

ST_NONE = 0     # no path to Station
ST_SELF = 1     # this is Station
ST_DIRECT = 2   # has a path to Station now

MAX_RECORD = 60

SEPARATOR = b"\x00"


@dataclass
class Caps:
    role: int = 0
    services: int = 0
    station: int = ST_NONE
    name: str = ""


def encode(caps: Caps) -> bytes:
    import cbor2

    record: dict = {"r": caps.role, "s": caps.services, "st": caps.station}
    if caps.name:
        record["n"] = caps.name[:24]
    return cbor2.dumps(record)


def app_data(marker: bytes, caps: Caps) -> bytes:
    """What goes in the announce: the old marker (may be empty), NUL, the record."""
    return bytes(marker) + SEPARATOR + encode(caps)


def split(app_data: Optional[bytes]) -> tuple[bytes, Optional[Caps]]:
    """(marker text, record or None). Old announces have no record."""
    if not app_data:
        return b"", None
    marker, sep, rest = bytes(app_data).partition(SEPARATOR)
    if not sep or not rest:
        return marker, None
    try:
        import cbor2

        record = cbor2.loads(rest)
        if not isinstance(record, dict):
            return marker, None
        return marker, Caps(role=int(record.get("r", 0)), services=int(record.get("s", 0)),
                            station=int(record.get("st", 0)), name=str(record.get("n", ""))[:24])
    except Exception:
        return marker, None


STATION_SERVICES = (SVC_DISPATCH | SVC_POSTBOX | SVC_NOTICEBOARD | SVC_BEACON | SVC_FIELDBOOK | SVC_COMMONS
                    | SVC_LOCKER | SVC_ROLLCALL | SVC_CORKBOARD | SVC_TRAILHEAD | SVC_SIGNAL | SVC_SYNC)
