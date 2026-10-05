"""Local stand-in for the Outpost's Wi-Fi Dispatch page API, for testing the
page (firmware/outpost/web/msg.*) in a desktop browser. Every login and
message signature the browser makes is checked with Station's own Python
code (server/services/identity), so a pass here means the browser's key
derivation and canonical bytes match Python's — and therefore the Scout's.

    python -m tools.outpost_web_mock [--port 8090]

then open http://127.0.0.1:8090/msg. "basecamp" / "blue canoe river" is a
vouched-for account (as if Station had sent its certificate); any other
login works but shows as not vouched for.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.services.identity import keys as K
from server.services.identity import objects as O

WEB = Path(__file__).resolve().parent.parent / "firmware" / "outpost" / "web"
NODE = "outpost-1-mock"
VOUCHED = {"basecamp": K.public_key("basecamp", "blue canoe river")}

nonces: dict[str, float] = {}
sessions: dict[str, dict] = {}
messages: list[dict] = []
checks = {"logins": 0, "messages": 0}


def verify(pub: bytes, sig: bytes, msg: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
        return True
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200, extra: dict | None = None) -> None:
        self._send(code, json.dumps(data).encode(), "application/json", extra)

    def _session(self) -> dict | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "wps" and v in sessions:
                return sessions[v]
        return None

    def do_GET(self):
        url = urlparse(self.path)
        files = {"/msg": ("msg.html", "text/html"), "/js/msg.js": ("msg.js", "text/javascript"),
                 "/js/wpcrypto.js": ("wpcrypto.js", "text/javascript"),
                 "/js/nacl.js": ("vendor/nacl-fast.min.js", "text/javascript"),
                 "/js/scrypt.js": ("vendor/scrypt.js", "text/javascript")}
        if url.path in files:
            name, ctype = files[url.path]
            return self._send(200, (WEB / name).read_bytes(), ctype)
        if url.path == "/api/hello":
            nonce = secrets.token_bytes(16).hex()
            nonces[nonce] = time.time() + 120
            return self._json({"node": NODE, "nonce": nonce})
        s = self._session()
        if not s:
            return self._json({"error": "not_signed_in"}, 401)
        if url.path == "/api/me":
            return self._json({"u": s["u"], "id": s["id"].hex(), "vouched": s["vouched"]})
        if url.path == "/api/convs":
            convs: dict[str, dict] = {}
            for m in messages:
                if s["u"].lower() in m["v"][3:].split(":"):
                    other = [p for p in m["v"][3:].split(":") if p != s["u"].lower()] or [s["u"]]
                    c = convs.setdefault(m["v"], {"id": m["v"], "with": other[0], "t": 0, "n": 0})
                    c["n"] += 1
                    c["t"] = max(c["t"], m["t"])
            return self._json({"convs": sorted(convs.values(), key=lambda c: -c["t"])})
        if url.path == "/api/msgs":
            conv = parse_qs(url.query).get("c", [""])[0]
            from server.services.sync.engine import max_signed_body

            peer = [p for p in conv[3:].split(":") if p != s["u"].lower()] if conv.startswith("dm:") else []
            limit = max_signed_body(peer[0] if peer else s["u"]) if conv.startswith("dm:") else max_signed_body(conv, room=True)
            return self._json({"msgs": [{"o": m["o"], "u": m["u"], "b": m["b"], "t": m["t"]}
                                        for m in messages if m["v"] == conv], "max": limit})
        self._json({"error": "not_found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        path = urlparse(self.path).path
        if path == "/api/login":
            nonce = body.get("n", "")
            if nonces.pop(nonce, 0) < time.time():
                return self._json({"error": "expired"}, 400)
            pub, sig = bytes.fromhex(body["p"]), bytes.fromhex(body["s"])
            msg = f"WAYPOST-WEB-LOGIN-1\n{NODE}\n".encode() + bytes.fromhex(nonce)
            if not verify(pub, sig, msg):
                return self._json({"error": "bad_signature"}, 400)
            user = body["u"].strip().lower()
            if user in VOUCHED and VOUCHED[user] != pub:
                return self._json({"error": "wrong_password"}, 400)
            checks["logins"] += 1
            token = secrets.token_hex(16)
            sessions[token] = {"u": user, "pub": pub, "id": K.identity_id(pub), "vouched": user in VOUCHED}
            s = sessions[token]
            return self._json({"ok": True, "u": user, "id": s["id"].hex(), "vouched": s["vouched"]},
                              extra={"Set-Cookie": f"wps={token}; Path=/; HttpOnly"})
        s = self._session()
        if not s:
            return self._json({"error": "not_signed_in"}, 401)
        if path == "/api/logout":
            for k, v in list(sessions.items()):
                if v is s:
                    del sessions[k]
            return self._json({"ok": True})
        if path == "/api/send":
            obj = {"k": O.KIND_DISPATCH_MSG, "o": bytes.fromhex(body["o"]), "u": s["u"], "a": s["id"],
                   "v": body["v"], "b": body["b"], "t": int(body["t"])}
            if not verify(s["pub"], bytes.fromhex(body["s"]), O.canonical_bytes(obj)):
                return self._json({"error": "bad_signature"}, 400)
            checks["messages"] += 1
            messages.append({"o": body["o"], "u": s["u"], "v": body["v"], "b": body["b"], "t": int(body["t"])})
            print(f"verified message from {s['u']} ({len(body['b'].encode())} bytes) — checks so far: {checks}")
            return self._json({"ok": True})
        self._json({"error": "not_found"}, 404)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()
    print(f"Outpost page mock on http://127.0.0.1:{args.port}/msg")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
