"""Bound devices prove their radio requests (shared/protocol/devauth.py,
review 2026-10-07). Before: a request naming a bound Scout as `src` was
trusted, so anyone with a radio — or, with the Pi Station, anyone on its
Wi-Fi — could unpair a Scout, send as its person or raise a Beacon."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.db import Database
from server.gateway.waylink import WaylinkGateway
from server.services.auth.pairing import PairingService
from server.services.auth.service import AuthService
from server.services.dispatch.service import DispatchService
from server.services.identity import certs as C
from server.services.identity import keys as K
from server.services.identity.service import IdentityService
from server.services.profiles.constants import OP_LOGIN, OP_LOGIN_NONCE, OP_UNPAIR, OP_WHOAMI
from server.transports.base import TransportPacket
from shared.protocol import devauth
from shared.protocol.envelope import SVC_PROFILE, Envelope, Flags, decode_cbor, encode_cbor

SCOUT = "pocket-1-e75a"
DEST = bytes.fromhex("e75a4c2818b4cd84b800d98827a11ed9")
PASSWORD = "blue canoe river"


class Capture:
    name = "capture"

    def __init__(self):
        self.sent: list[Envelope] = []

    async def send(self, packet: TransportPacket) -> None:
        self.sent.append(decode_cbor(packet.payload))

    def resolve_destination(self, destination: str) -> str:
        return destination


@pytest.fixture()
def world(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    dispatch = DispatchService(db.dispatch)
    ident = IdentityService(db.identity, C.CommunityKey.generate(), get_binding=db.dispatch.get_binding,
                            get_user=db.get_user_by_username)
    auth = AuthService(db)
    auth.on_password = ident.record_password
    auth.register(username="basecamp", password=PASSWORD)
    pairing = PairingService(db, dispatch)
    pairing.identity = ident
    transport = Capture()
    gw = WaylinkGateway(transport)
    for op in (OP_LOGIN_NONCE, OP_LOGIN, OP_UNPAIR, OP_WHOAMI):
        gw.register(SVC_PROFILE, op, pairing.handle_rpc)
    required = {"on": True}

    def verify(env):
        b = db.dispatch.get_binding(str(env.src))
        if not b:
            return True
        if b.get("device_key"):
            return devauth.check(bytes.fromhex(b["device_key"]), str(env.src), str(env.mid))
        return not required["on"]

    gw.verify_src = verify
    return db, gw, transport, required


async def request(gw, transport, op, payload, *, mid=None):
    env = Envelope(src=SCOUT, dst="station", svc=SVC_PROFILE, op=op, flags=int(Flags.REQUEST), payload=payload)
    if mid:
        env.mid = mid
    await gw._handle_packet(TransportPacket(destination="station", payload=encode_cbor(env), source=SCOUT))
    return transport.sent[-1]


async def sign_in(gw, transport):
    nonce = (await request(gw, transport, OP_LOGIN_NONCE, {})).payload["nonce"]
    sig = K.private_key("basecamp", PASSWORD).sign(PairingService.login_bytes(SCOUT, DEST, nonce))
    r = await request(gw, transport, OP_LOGIN, {"u": "basecamp", "rd": DEST, "sig": sig})
    assert r.payload["ok"]
    return r.payload["dk"]


async def test_sign_in_hands_the_device_its_key(world):
    db, gw, transport, _ = world
    key = await sign_in(gw, transport)
    assert len(key) == devauth.KEY_LEN and db.dispatch.get_binding(SCOUT)["device_key"] == key.hex()


async def test_a_forger_cannot_act_as_a_bound_device(world):
    db, gw, transport, _ = world
    key = await sign_in(gw, transport)
    # Someone else names the Scout but can't tag the request.
    r = await request(gw, transport, OP_UNPAIR, {}, mid="0123456789abcdef")
    assert db.dispatch.get_binding(SCOUT)  # still bound
    assert r.dst == SCOUT  # the answer goes to the real Scout, not the forger
    r = await request(gw, transport, OP_WHOAMI, {}, mid=devauth.make_mid(b"x" * 16, SCOUT))
    assert r.payload.get("error") == "not_paired"
    # The Scout itself, with its key.
    r = await request(gw, transport, OP_WHOAMI, {}, mid=devauth.make_mid(key, SCOUT))
    assert r.payload["username"] == "basecamp"
    await request(gw, transport, OP_UNPAIR, {}, mid=devauth.make_mid(key, SCOUT))
    assert db.dispatch.get_binding(SCOUT) is None


async def test_bindings_from_before_keys(world):
    db, gw, transport, required = world
    db.dispatch.bind_device(SCOUT, "basecamp", transport_dest=DEST.hex())  # no key
    r = await request(gw, transport, OP_WHOAMI, {})
    assert r.payload.get("error") == "not_paired"  # production: sign in again for a key
    required["on"] = False  # lab / tests
    r = await request(gw, transport, OP_WHOAMI, {})
    assert r.payload["username"] == "basecamp"


def test_tags():
    key = devauth.new_key()
    mid = devauth.make_mid(key, SCOUT)
    assert len(mid) == 16 and devauth.check(key, SCOUT, mid)
    assert not devauth.check(key, "pocket-1-ffff", mid)  # bound to the node it names
    assert not devauth.check(devauth.new_key(), SCOUT, mid)
    assert not devauth.check(key, SCOUT, "zz" * 8) and not devauth.check(key, SCOUT, "short")
    # Pinned vector: firmware/scout/src/net.cpp computes the same.
    assert devauth.tag(bytes(range(16)), SCOUT, "0a1b2c3d") == VECTOR_TAG


VECTOR_TAG = "1901d391"
