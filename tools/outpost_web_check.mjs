// Runs the Outpost page's own crypto (firmware/outpost/web/wpcrypto.js with
// the vendored tweetnacl + scrypt-js) under Node against the Python
// stand-in (tools/outpost_web_mock.py), which checks every signature with
// Station's code. Also checks the derived key against the pinned vector in
// server/tests/test_identity_keys.py.
//
//   python -m tools.outpost_web_mock &   node tools/outpost_web_check.mjs
import { readFileSync } from "node:fs";
import vm from "node:vm";

const WEB = new URL("../firmware/outpost/web/", import.meta.url);
globalThis.self = globalThis;
globalThis.window = globalThis;
for (const f of ["vendor/nacl-fast.min.js", "vendor/scrypt.js", "wpcrypto.js"])
  vm.runInThisContext(readFileSync(new URL(f, WEB), "utf8"), { filename: f });
const { hex, deriveKey, loginBytes, messageBytes, te } = globalThis.wpcrypto;
const nacl = globalThis.nacl;
const BASE = process.env.MOCK || "http://127.0.0.1:8090";
let cookie = "";

async function api(path, body) {
  const r = await fetch(BASE + path, body === undefined ? { headers: { cookie } } : {
    method: "POST", headers: { "Content-Type": "application/json", cookie }, body: JSON.stringify(body) });
  const set = r.headers.get("set-cookie");
  if (set) cookie = set.split(";")[0];
  return r.json();
}
function check(label, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
  if (!ok) process.exitCode = 1;
}

const t0 = Date.now();
const kp = await deriveKey("Basecamp", "blue canoe river");
check("key from username + password matches Python's pinned vector",
  hex(kp.publicKey) === "c429d72f6ecb1bb2ce838d07e4cb8e1e757a52a78560b1b822e3c267533e6708",
  `(${Date.now() - t0} ms)`);

let hello = await api("/api/hello");
let r = await api("/api/login", { u: "basecamp", p: hex(kp.publicKey), n: hello.nonce,
  s: hex(nacl.sign.detached(loginBytes(hello.node, hello.nonce), kp.secretKey)) });
check("sign-in accepted (challenge signature checked by Python)", r.ok === true && r.vouched === true, JSON.stringify(r));
check("identity id is SHA-256(key)[:16] as Python computes it", r.id === "c7a7953330f8c28e3ba64498b3e9f6da", r.id);

const me = r;
const conv = "dm:basecamp:ridgeline";
const msgs = await api("/api/msgs?c=" + encodeURIComponent(conv));
const body = "From the Outpost page: water at the north tap. Ünïcode ok?";
const o = nacl.randomBytes(16), t = Math.floor(Date.now() / 1000);
const b = te.encode(body);
r = await api("/api/send", { o: hex(o), v: conv, b: body, t,
  s: hex(nacl.sign.detached(messageBytes(o, me.u, me.id, conv, b, t), kp.secretKey)) });
check("signed message accepted (canonical bytes checked by Python)", r.ok === true, JSON.stringify(r));
check("compose limit offered", msgs.max >= 100 && msgs.max <= 140, `max=${msgs.max}`);

const wrong = await deriveKey("basecamp", "not the password");
hello = await api("/api/hello");
r = await api("/api/login", { u: "basecamp", p: hex(wrong.publicKey), n: hello.nonce,
  s: hex(nacl.sign.detached(loginBytes(hello.node, hello.nonce), wrong.secretKey)) });
check("wrong password refused", r.error === "wrong_password", JSON.stringify(r));
