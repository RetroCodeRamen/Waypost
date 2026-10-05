// Outpost Dispatch page. Identity = key derived from username + password
// (server/services/identity/keys.py), worked out here in the browser so the
// password never leaves the phone. The key proves who you are at sign-in
// (signs the Outpost's one-time challenge) and signs every message you send
// (server/services/identity/objects.py canonical bytes) — the same bytes a
// Scout or Station checks. The key lives only in this tab's session.
"use strict";

const { te, hex, unhex, dmId, deriveKey, loginBytes, messageBytes } = wpcrypto;
const $ = (id) => document.getElementById(id);

let me = null;  // { u, id (hex), vouched, sk (Uint8Array) }
function remember() {
  if (me) sessionStorage.setItem("wp_me", JSON.stringify({ u: me.u, id: me.id, vouched: me.vouched, sk: hex(me.sk) }));
  else sessionStorage.removeItem("wp_me");
}
function recall() {
  try {
    const s = JSON.parse(sessionStorage.getItem("wp_me") || "null");
    if (s) me = { u: s.u, id: s.id, vouched: s.vouched, sk: unhex(s.sk) };
  } catch (e) { me = null; }
}

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty */ }
  if (!r.ok && !data.error) data.error = `HTTP ${r.status}`;
  return data;
}

function explain(error) {
  return ({
    wrong_password: "That password doesn't match this account.",
    bad_signature: "The Outpost couldn't check that signature.",
    expired: "That sign-in took too long — try again.",
    too_long: "That message is too long for the radio.",
    not_signed_in: "Your session ended — sign in again.",
    full: "Too many people are signed in here right now — try again shortly.",
  })[error] || error;
}

// -- sign in -------------------------------------------------------------------------
async function signIn() {
  const u = $("u").value.trim(), pw = $("pw").value;
  const status = $("login-status");
  status.className = "status";
  if (!u || !pw) { status.textContent = "Username and password, please."; return; }
  $("signin").disabled = true;
  try {
    status.textContent = "Working out your key…";
    const kp = await deriveKey(u, pw, (p) => { status.textContent = `Working out your key… ${Math.round(p * 100)}%`; });
    $("pw").value = "";
    status.textContent = "Signing in…";
    const hello = await api("/api/hello");
    if (hello.error) throw new Error(hello.error);
    const sig = nacl.sign.detached(loginBytes(hello.node, hello.nonce), kp.secretKey);
    const r = await api("/api/login", { u, p: hex(kp.publicKey), n: hello.nonce, s: hex(sig) });
    if (r.error) throw new Error(r.error);
    me = { u: r.u, id: r.id, vouched: r.vouched, sk: kp.secretKey };
    remember();
    status.textContent = "";
    show();
  } catch (e) {
    status.className = "status err";
    status.textContent = explain(e.message);
  } finally {
    $("signin").disabled = false;
  }
}

async function signOut() {
  await api("/api/logout", {});
  me = null;
  remember();
  show();
}

// -- conversations ------------------------------------------------------------------------
let openConv = null, openWith = null, maxBody = 120, timer = null;

async function loadConvs() {
  const r = await api("/api/convs");
  if (r.error === "not_signed_in") return expired();
  const ul = $("convs");
  ul.innerHTML = "";
  for (const c of r.convs || []) {
    const li = document.createElement("li");
    li.className = "conv";
    li.innerHTML = `<span></span><span class="note"></span>`;
    li.firstChild.textContent = c.with || c.id;
    li.lastChild.textContent = c.n + (c.n === 1 ? " message" : " messages");
    li.onclick = () => openChat(c.id, c.with || c.id);
    ul.appendChild(li);
  }
  $("empty").classList.toggle("hidden", (r.convs || []).length > 0);
}

async function openChat(conv, withName) {
  openConv = conv;
  openWith = withName;
  $("list").classList.add("hidden");
  $("chat").classList.remove("hidden");
  $("chat-with").textContent = withName;
  $("chat-status").textContent = "";
  await loadMsgs();
}

function backToList() {
  openConv = null;
  $("chat").classList.add("hidden");
  $("list").classList.remove("hidden");
  loadConvs();
}

async function loadMsgs() {
  if (!openConv) return;
  const r = await api("/api/msgs?c=" + encodeURIComponent(openConv));
  if (r.error === "not_signed_in") return expired();
  maxBody = r.max || maxBody;
  const box = $("msgs");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  box.innerHTML = "";
  for (const m of r.msgs || []) {
    const div = document.createElement("div");
    const mine = m.u.toLowerCase() === me.u.toLowerCase();
    div.className = "msg" + (mine ? " mine" : "");
    div.textContent = m.b;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = (mine ? "you" : m.u) + (m.t > 1 ? " · " + new Date(m.t * 1000).toLocaleString() : "") +
      (mine && m.d ? " · delivered" : "");
    div.appendChild(meta);
    box.appendChild(div);
  }
  if (!(r.msgs || []).length) box.innerHTML = '<p class="note">No messages yet — say hello.</p>';
  if (atBottom) box.scrollTop = box.scrollHeight;
  count();
}

function count() {
  const n = te.encode($("body").value).length;
  $("count").textContent = `${n}/${maxBody}`;
  $("send").disabled = n === 0 || n > maxBody;
}

async function send() {
  const body = $("body").value;
  const b = te.encode(body);
  if (!b.length || b.length > maxBody) return;
  $("send").disabled = true;
  const o = nacl.randomBytes(16);
  const t = Math.floor(Date.now() / 1000);
  const s = nacl.sign.detached(messageBytes(o, me.u, me.id, openConv, b, t), me.sk);
  const r = await api("/api/send", { o: hex(o), v: openConv, b: body, t, s: hex(s) });
  if (r.error) {
    $("chat-status").className = "status err";
    $("chat-status").textContent = explain(r.error);
    if (r.error === "not_signed_in") return expired();
  } else {
    $("chat-status").className = "status";
    $("chat-status").textContent = "Sent — delivered to people nearby now, everyone else as the radio reaches them.";
    $("body").value = "";
  }
  count();
  await loadMsgs();
}

function expired() {
  me = null;
  remember();
  show();
  $("login-status").className = "status err";
  $("login-status").textContent = explain("not_signed_in");
}

function show() {
  clearInterval(timer);
  $("login").classList.toggle("hidden", !!me);
  $("app").classList.toggle("hidden", !me);
  if (!me) return;
  $("me").textContent = `Signed in as ${me.u}` + (me.vouched ? "" : " — Station hasn't vouched for this key here yet");
  backToList();
  timer = setInterval(() => (openConv ? loadMsgs() : loadConvs()), 4000);
}

$("signin").onclick = signIn;
$("pw").addEventListener("keydown", (e) => { if (e.key === "Enter") signIn(); });
$("signout").onclick = signOut;
$("new").onclick = () => $("new-form").classList.toggle("hidden");
$("open").onclick = () => {
  const to = $("to").value.trim().toLowerCase();
  if (to) openChat(dmId(me.u, to), to);
};
$("back").onclick = backToList;
$("body").addEventListener("input", count);
$("send").onclick = send;

recall();
// A remembered key is only good with a live session on this Outpost.
if (me) api("/api/me").then((r) => { if (r.error) { me = null; remember(); } show(); });
else show();
