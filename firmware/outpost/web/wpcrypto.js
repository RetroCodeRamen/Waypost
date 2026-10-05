// Waypost identity and message signing for the Outpost page — pure functions,
// no DOM, so the same file runs in the browser and under Node
// (tools/outpost_web_check.mjs checks it against Station's Python code).
// Needs tweetnacl (nacl) and scrypt-js (scrypt) loaded first.
"use strict";

(function (root) {
const te = new TextEncoder();
const td = new TextDecoder();

// -- bytes --------------------------------------------------------------------
const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const unhex = (h) => new Uint8Array((h.match(/../g) || []).map((x) => parseInt(x, 16)));
function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let i = 0;
  for (const p of parts) { out.set(p, i); i += p.length; }
  return out;
}
function u64be(n) {
  const out = new Uint8Array(8);
  let hi = Math.floor(n / 4294967296), lo = n >>> 0;
  for (let i = 7; i >= 4; i--) { out[i] = lo & 255; lo >>>= 8; }
  for (let i = 3; i >= 0; i--) { out[i] = hi & 255; hi >>>= 8; }
  return out;
}
// name:len:value — server/services/identity/certs.py canonical_bytes
function field(name, value) {
  const n = te.encode(name);
  return concat(n, new Uint8Array([58, value.length >> 8, value.length & 255]), value);
}
function dmId(a, b) {
  const x = a.toLowerCase(), y = b.toLowerCase();
  return x < y ? `dm:${x}:${y}` : `dm:${y}:${x}`;
}

// -- identity -------------------------------------------------------------------
const SCRYPT = { N: 4096, r: 8, p: 4 };  // keys.py — never change without a new salt prefix
async function deriveKey(username, password, progress) {
  const salt = te.encode("waypost-identity-v1\n" + username.trim().toLowerCase());
  const seed = await scrypt.scrypt(te.encode(password), salt, SCRYPT.N, SCRYPT.r, SCRYPT.p, 32, progress);
  return nacl.sign.keyPair.fromSeed(seed);
}


  const nacl = root.nacl, scrypt = root.scrypt;

  function loginBytes(node, nonceHex) {
    return concat(te.encode(`WAYPOST-WEB-LOGIN-1\n${node}\n`), unhex(nonceHex));
  }

  // objects.py canonical_bytes, kind dispatch.msg: k o u a v b t
  function messageBytes(o, u, idHex, conv, bodyBytes, t) {
    return concat(te.encode("WAYPOST-OBJ-1\n"), field("k", te.encode("dispatch.msg")), field("o", o),
      field("u", te.encode(u)), field("a", unhex(idHex)), field("v", te.encode(conv)), field("b", bodyBytes),
      field("t", u64be(t)));
  }

  root.wpcrypto = { te, td, hex, unhex, concat, u64be, field, dmId, SCRYPT, deriveKey, loginBytes, messageBytes };
})(typeof window !== "undefined" ? window : globalThis);
