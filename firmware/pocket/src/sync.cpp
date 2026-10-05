#include "sync.h"

#include <algorithm>
#include <cstdio>
#include <map>
#include <vector>

#include <Arduino.h>

#include "account.h"
#include "app.h"
#include "certs.h"
#include "contacts.h"
#include "station_link.h"
#include "store.h"

namespace peersync {
namespace {

using waylink::Value;

const size_t kListUnder = 10;  // engine.py LIST_UNDER
const size_t kFpLen = 8;       // engine.py FP_LEN
const size_t kMaxDepth = 8;
const uint32_t kStationEveryMs = 3UL * 60UL * 1000UL;
const uint32_t kPeerEveryMs = 3UL * 60UL * 1000UL;

struct Obj {
  std::string o, u, a, v, b, s;  // a: author's identity id (16 bytes)
  uint64_t t = 0;
};

std::string lower(std::string s) {
  for (auto& ch : s) ch = static_cast<char>(tolower(static_cast<unsigned char>(ch)));
  return s;
}

std::string hex(const std::string& raw) {
  static const char* d = "0123456789abcdef";
  std::string out;
  for (unsigned char c : raw) {
    out += d[c >> 4];
    out += d[c & 15];
  }
  return out;
}

std::string unhex(const std::string& h) {
  std::string out;
  for (size_t i = 0; i + 1 < h.size(); i += 2) out += static_cast<char>(strtoul(h.substr(i, 2).c_str(), nullptr, 16));
  return out;
}

std::string dm_id(const std::string& a, const std::string& b) {
  std::string x = lower(a), y = lower(b);
  return x < y ? "dm:" + x + ":" + y : "dm:" + y + ":" + x;
}

// -- scopes (engine.py parties / in_scope) ------------------------------------------

std::vector<std::string> parties(const std::string& author, const std::string& conv) {
  std::vector<std::string> out{lower(author)};
  if (conv.compare(0, 3, "dm:") == 0) {
    size_t colon = conv.find(':', 3);
    if (colon != std::string::npos) {
      out.push_back(lower(conv.substr(3, colon - 3)));
      out.push_back(lower(conv.substr(colon + 1)));
    }
  }
  return out;
}

bool in_scope(const std::string& scope, const std::string& author, const std::string& conv) {
  if (scope == "*") return true;
  if (scope.compare(0, 2, "u:") == 0) {
    auto p = parties(author, conv);
    return std::find(p.begin(), p.end(), lower(scope.substr(2))) != p.end();
  }
  if (scope.compare(0, 2, "c:") == 0) return conv == scope.substr(2);
  return false;
}

bool wants(const std::vector<std::string>& interests, const std::string& author, const std::string& conv) {
  for (const auto& q : interests)
    if (in_scope(q, author, conv)) return true;
  return false;
}

std::vector<std::string> my_interests() {
  std::vector<std::string> out{"u:" + lower(account::username())};
  for (const auto& c : store::conversations())
    if (c.id.compare(0, 5, "room:") == 0) out.push_back("c:" + c.id);
  return out;
}

std::vector<std::string> held_scopes(const std::vector<std::string>& interests) {
  std::vector<std::string> out;
  for (const auto& r : store::signed_refs()) {
    if (wants(interests, r.author, r.conv)) continue;
    for (const auto& p : parties(r.author, r.conv))
      if (std::find(out.begin(), out.end(), "u:" + p) == out.end()) out.push_back("u:" + p);
  }
  return out;
}

// -- this Scout's objects ---------------------------------------------------------------

std::vector<std::string> oids(const std::string& scope) {
  std::vector<std::string> out;
  for (const auto& r : store::signed_refs())
    if (in_scope(scope, r.author, r.conv)) out.push_back(r.oid);
  return out;
}

bool get(const std::string& oid, Obj& out) {
  std::string conv;
  store::Message m;
  if (!store::find_signed(oid, conv, m)) return false;
  out.o = oid;
  out.u = m.sender;
  out.v = conv;
  out.b = m.body;
  out.s = m.sig;
  out.a = m.author_id;
  out.t = m.signed_t;
  return true;
}

// Verified, then kept. Returns "" (stored or already here) or an error.
std::string put(const Obj& obj, bool& created) {
  created = false;
  std::string err = certs::verify_dispatch(obj.o, obj.u, obj.a, obj.v, obj.b, obj.t, obj.s);
  if (!err.empty()) return err;
  store::Message m;
  m.id = hex(obj.o);
  m.sender = obj.u;
  m.body = obj.b;
  uint64_t now = station_link::now_ms();
  m.ts = now ? now : obj.t * 1000ULL;
  m.state = lower(obj.u) == lower(account::username()) ? 's' : 'r';
  m.sig = obj.s;
  m.author_id = obj.a;
  m.signed_t = obj.t;
  created = apps::deliver_message(obj.v, m);
  return "";
}

Value to_wire(const Obj& obj) {
  Value w = Value::make_map();
  w.set("o", Value::of_bytes(obj.o));
  w.set("a", Value::of_bytes(obj.a));
  w.set("b", Value::of_text(obj.b));
  w.set("t", Value::of_uint(obj.t));
  w.set("s", Value::of_bytes(obj.s));
  if (obj.v.compare(0, 3, "dm:") == 0) {
    auto p = parties(obj.u, obj.v);  // [author, a, b]
    w.set("p", Value::of_text(p[1] == lower(obj.u) ? p[2] : p[1]));
  } else {
    w.set("v", Value::of_text(obj.v));
  }
  return w;
}

bool from_wire(const Value& w, Obj& obj) {
  obj.a = w.bytes("a");
  obj.u = certs::owner_of(obj.a);  // unknown: looked up from Station later
  if (obj.u.empty()) return false;
  obj.o = w.bytes("o");
  obj.b = w.text("b");
  obj.t = w.uint("t");
  obj.s = w.bytes("s");
  std::string v = w.text("v");
  obj.v = v.empty() ? dm_id(obj.u, w.text("p")) : v;
  return obj.o.size() == 16 && obj.s.size() == 64;
}

// -- summaries (engine.py summarize) ----------------------------------------------------

std::vector<std::string> under(const std::vector<std::string>& ids, const std::string& prefix) {
  std::vector<std::string> out;
  for (const auto& o : ids)
    if (hex(o).compare(0, prefix.size(), prefix) == 0) out.push_back(o);
  return out;
}

std::string fingerprint(const std::vector<std::string>& ids) {
  std::string acc(kFpLen, '\0');
  for (const auto& o : ids)
    for (size_t i = 0; i < kFpLen && i < o.size(); i++) acc[i] ^= o[i];
  return acc;
}

Value summarize(const std::vector<std::string>& ids, const std::string& prefix) {
  auto mine = under(ids, prefix);
  Value out = Value::make_map();
  out.set("n", Value::of_uint(mine.size()));
  out.set("x", Value::of_bytes(fingerprint(mine)));
  if (mine.size() <= kListUnder || prefix.size() >= kMaxDepth) {
    std::sort(mine.begin(), mine.end());
    Value list = Value::make_array();
    for (const auto& o : mine) list.push(Value::of_bytes(o));
    out.set("oids", list);
  } else {
    Value sub = Value::make_array();
    for (const char* d = "0123456789abcdef"; *d; d++) {
      auto b = under(mine, prefix + *d);
      Value pair = Value::make_array();
      pair.push(Value::of_uint(b.size()));
      pair.push(Value::of_bytes(fingerprint(b)));
      sub.push(pair);
    }
    out.set("sub", sub);
  }
  return out;
}

Value string_list(const std::vector<std::string>& v) {
  Value out = Value::make_array();
  for (const auto& s : v) out.push(Value::of_text(s));
  return out;
}

std::vector<std::string> strings_of(const Value* v) {
  std::vector<std::string> out;
  if (v && v->type == Value::Array)
    for (const auto& i : v->items)
      if (i.type == Value::Text) out.push_back(i.s);
  return out;
}

// -- responder ----------------------------------------------------------------------------

std::map<std::string, RNS::Bytes> g_reply_to;  // peer node id -> its destination (from HELLO rd)

void reply(const waylink::Reply& req, const RNS::Bytes& to, const Value& payload, bool error) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  RNS::Bytes bytes = waylink::encode_envelope(station_link::node_id().c_str(), src.c_str(),
                                              waylink::new_hex_id(), req.rid, "SYNC", op.c_str(),
                                              error ? 2 | 4 : 2, 120, 0, payload);
  if (bytes.size() > waylink::kRadioMdu) Serial.printf("sync: %s reply too big (%u)\n", op.c_str(), bytes.size());
  station_link::send_to(to, bytes);
}

// -- initiator ----------------------------------------------------------------------------

struct Session {
  RNS::Bytes dest;
  std::string node;
  Result res;
  std::vector<std::string> mine_interests, theirs;
  std::vector<std::string> pull, push;

  bool ask(const char* op, const Value& payload, waylink::Reply& out) {
    res.requests++;
    auto r = station_link::request_peer(dest, node.c_str(), "SYNC", op, payload, out);
    if (r == station_link::Result::Ok || r == station_link::Result::Error) return true;
    res.ok = false;
    return false;
  }

  bool pull_ok(const std::string& q) const {
    return std::find(mine_interests.begin(), mine_interests.end(), q) != mine_interests.end();
  }
  bool push_ok(const std::string& q) const {
    return std::find(theirs.begin(), theirs.end(), "*") != theirs.end() ||
           std::find(theirs.begin(), theirs.end(), q) != theirs.end();
  }
  static void add_unique(std::vector<std::string>& v, const std::string& x) {
    if (std::find(v.begin(), v.end(), x) == v.end()) v.push_back(x);
  }

  bool walk(const std::string& scope, const std::string& prefix) {
    auto mine = under(oids(scope), prefix);
    Value q = Value::make_map();
    q.set("q", Value::of_text(scope));
    q.set("p", Value::of_text(prefix));
    waylink::Reply r;
    if (!ask("SUM", q, r) || !r.error.empty()) return false;
    const Value& p = r.payload();
    if (p.uint("n") == mine.size() && p.bytes("x") == fingerprint(mine)) return true;
    const Value* list = p.get("oids");
    if (list && list->type == Value::Array) {
      std::vector<std::string> theirs_here;
      for (const auto& i : list->items) theirs_here.push_back(i.s);
      for (const auto& o : theirs_here)
        if (pull_ok(scope) && std::find(mine.begin(), mine.end(), o) == mine.end()) add_unique(pull, o);
      for (const auto& o : mine)
        if (push_ok(scope) && std::find(theirs_here.begin(), theirs_here.end(), o) == theirs_here.end())
          add_unique(push, o);
      return true;
    }
    const Value* sub = p.get("sub");
    if (!sub || sub->type != Value::Array || sub->items.size() != 16) return false;
    for (int d = 0; d < 16; d++) {
      const Value& pair = sub->items[d];
      if (pair.type != Value::Array || pair.items.size() != 2) return false;
      std::string child_prefix = prefix + "0123456789abcdef"[d];
      auto child = under(mine, child_prefix);
      uint64_t n = pair.items[0].u;
      if (n == child.size() && pair.items[1].s == fingerprint(child)) continue;
      if (n == 0) {
        if (push_ok(scope))
          for (const auto& o : child) add_unique(push, o);
        continue;
      }
      if (child.empty() && !pull_ok(scope)) continue;
      if (child_prefix.size() > kMaxDepth || !walk(scope, child_prefix)) return false;
    }
    return true;
  }
};

uint32_t g_station_at = 0;
std::map<std::string, uint32_t> g_peer_at;  // contact -> last sync millis

bool due(uint32_t at, uint32_t every) { return at == 0 || millis() - at >= every; }

}  // namespace

Result with(const RNS::Bytes& dest, const std::string& node) {
  Session s;
  s.dest = dest;
  s.node = node;
  if (!account::paired() || !store::files_safe()) {
    s.res.ok = false;
    return s.res;
  }
  s.mine_interests = my_interests();

  Value hello = Value::make_map();
  hello.set("r", Value::of_text("scout"));
  hello.set("i", string_list(s.mine_interests));
  hello.set("h", string_list(held_scopes(s.mine_interests)));
  hello.set("rd", Value::of_bytes(unhex(station_link::dest_hex())));
  waylink::Reply r;
  if (!s.ask("HELLO", hello, r) || !r.error.empty()) return s.res;
  s.theirs = strings_of(r.payload().get("i"));
  auto their_held = strings_of(r.payload().get("h"));

  std::vector<std::string> scopes;
  auto consider = [&](const std::vector<std::string>& v) {
    for (const auto& q : v)
      if (q != "*" && (s.pull_ok(q) || s.push_ok(q))) Session::add_unique(scopes, q);
  };
  consider(s.mine_interests);
  consider(s.theirs);
  consider(held_scopes(s.mine_interests));
  consider(their_held);

  for (const auto& q : scopes)
    if (!s.walk(q, "")) return s.res;

  for (const auto& oid : s.pull) {
    Value q = Value::make_map();
    q.set("o", Value::of_bytes(oid));
    waylink::Reply w;
    if (!s.ask("WANT", q, w)) return s.res;
    if (!w.error.empty() || w.payload().flag("missing")) continue;
    Obj obj;
    if (!from_wire(w.payload(), obj)) {
      s.res.rejected++;
      continue;
    }
    if (!wants(s.mine_interests, obj.u, obj.v)) continue;
    bool created = false;
    std::string err = put(obj, created);
    if (!err.empty()) {
      Serial.printf("sync: refused %s: %s\n", hex(oid).substr(0, 8).c_str(), err.c_str());
      s.res.rejected++;
    } else if (created) {
      s.res.pulled++;
    }
  }

  for (const auto& oid : s.push) {
    Obj obj;
    if (!get(oid, obj) || !(s.push_ok("*") || wants(s.theirs, obj.u, obj.v))) continue;
    waylink::Reply w;
    if (!s.ask("PUT", to_wire(obj), w)) return s.res;
    if (!w.error.empty()) {
      Serial.printf("sync: peer refused %s: %s\n", hex(oid).substr(0, 8).c_str(), w.error.c_str());
      s.res.rejected++;
    } else if (w.payload().flag("new")) {
      s.res.pushed++;
    }
  }
  return s.res;
}

void handle(const waylink::Reply& req) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  const Value& p = req.payload();
  if (op == "HELLO") {
    std::string rd = p.bytes("rd");
    if (rd.size() == 16) g_reply_to[src] = RNS::Bytes(reinterpret_cast<const uint8_t*>(rd.data()), rd.size());
  }
  RNS::Bytes to;
  if (src == station_link::kStationNodeId) to = station_link::station_dest();
  else if (g_reply_to.count(src)) to = g_reply_to[src];
  if (to.size() != 16) {
    Serial.printf("sync: %s from %s, but no way to reply (no HELLO)\n", op.c_str(), src.c_str());
    return;
  }
  if (!account::paired() || !store::files_safe()) {
    Value e = Value::make_map();
    e.set("error", Value::of_text("not_ready"));
    reply(req, to, e, true);
    return;
  }

  if (op == "HELLO") {
    auto mine = my_interests();
    Value out = Value::make_map();
    out.set("r", Value::of_text("scout"));
    out.set("i", string_list(mine));
    out.set("h", string_list(held_scopes(mine)));
    reply(req, to, out, false);
  } else if (op == "SUM") {
    reply(req, to, summarize(oids(p.text("q")), lower(p.text("p"))), false);
  } else if (op == "WANT") {
    Obj obj;
    if (get(p.bytes("o"), obj)) {
      reply(req, to, to_wire(obj), false);
    } else {
      Value out = Value::make_map();
      out.set("missing", Value::of_bool(true));
      reply(req, to, out, false);
    }
  } else if (op == "PUT") {
    Obj obj;
    Value out = Value::make_map();
    if (!from_wire(p, obj)) {
      out.set("error", Value::of_text("unknown_identity"));
      reply(req, to, out, true);
      return;
    }
    bool created = false;
    std::string err = put(obj, created);
    if (!err.empty()) {
      Serial.printf("sync: refused a PUT from %s: %s\n", src.c_str(), err.c_str());
      out.set("error", Value::of_text(err));
      reply(req, to, out, true);
      return;
    }
    out.set("ok", Value::of_bool(true));
    out.set("new", Value::of_bool(created));
    reply(req, to, out, false);
  } else {
    Value out = Value::make_map();
    out.set("error", Value::of_text("unknown_op:" + op));
    reply(req, to, out, true);
  }
}

size_t largest_packet(const std::string& conv, const std::string& peer, size_t body_len) {
  Obj probe;
  probe.o.assign(16, '\0');
  probe.a.assign(16, '\0');
  probe.s.assign(64, '\0');
  probe.t = 4000000000ULL;
  probe.u = account::username();
  probe.v = conv;
  probe.b.assign(body_len, 'x');
  (void)peer;
  Value wire = to_wire(probe);
  const char* node = "pocket-1-xxxx";  // the longest node ids
  size_t put = waylink::encode_envelope(node, node, "0123456789abcdef", "0123456789abcdef", "SYNC", "PUT", 1,
                                        120, 4000000000ULL, wire).size();
  size_t want = waylink::encode_envelope(node, node, "0123456789abcdef", "0123456789abcdef", "SYNC", "WANT", 2,
                                         120, 4000000000ULL, wire).size();
  return put > want ? put : want;
}

void loop() {
  if (!account::paired() || !store::files_safe() || !station_link::ready() || !certs::idle()) return;
  // Station: the archive. Catch-up (MSG_SYNC) still covers unsigned messages.
  if (station_link::station_known() && due(g_station_at, kStationEveryMs)) {
    g_station_at = millis() | 1;
    Result r = with(station_link::station_dest(), station_link::kStationNodeId);
    Serial.printf("sync: Station %s, %d request(s), pulled %d, pushed %d, refused %d\n",
                  r.ok ? "done" : "interrupted", r.requests, r.pulled, r.pushed, r.rejected);
    return;  // one peer per loop
  }
  // Contacts whose Scouts are in range (their path is known): Scout to
  // Scout, no Station needed.
  for (const auto& c : contacts::all()) {
    if (c.scout_dest.size() != 32) continue;
    RNS::Bytes dest;
    dest.assignHex(c.scout_dest.c_str());
    if (!station_link::has_path(dest) || !due(g_peer_at[c.username], kPeerEveryMs)) continue;
    g_peer_at[c.username] = millis() | 1;
    Result r = with(dest, "scout:" + c.username);
    Serial.printf("sync: %s's Scout %s, %d request(s), pulled %d, pushed %d, refused %d\n",
                  c.username.c_str(), r.ok ? "done" : "interrupted", r.requests, r.pulled, r.pushed,
                  r.rejected);
    return;
  }
}

}  // namespace peersync
