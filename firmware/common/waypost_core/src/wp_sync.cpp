#include "wp_sync.h"

#include <algorithm>

#include <Arduino.h>

#include "wp_objects.h"

namespace wp {

using waylink::Reply;
using waylink::Value;

namespace {

const size_t kListUnder = 10;  // engine.py LIST_UNDER
const size_t kFpLen = 8;       // engine.py FP_LEN
const size_t kMaxDepth = 8;

void add_unique(std::vector<std::string>& v, const std::string& x) {
  if (std::find(v.begin(), v.end(), x) == v.end()) v.push_back(x);
}

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

Value error(const std::string& code) {
  Value out = Value::make_map();
  out.set("error", Value::of_text(code));
  return out;
}

}  // namespace

// -- scopes ---------------------------------------------------------------------------

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

std::vector<std::string> ObjectSet::oids(const std::string& scope) {
  std::vector<std::string> out;
  for (const auto& r : refs())
    if (in_scope(scope, r.author, r.conv)) out.push_back(r.oid);
  return out;
}

std::vector<std::string> ObjectSet::held_scopes(const std::vector<std::string>& mine) {
  std::vector<std::string> out;
  if (std::find(mine.begin(), mine.end(), "*") != mine.end()) return out;  // takes everything: not listed
  for (const auto& r : refs()) {
    if (wants(mine, r.author, r.conv)) continue;
    for (const auto& p : parties(r.author, r.conv)) add_unique(out, "u:" + p);
  }
  return out;
}

// -- wire form (engine.py to_wire / from_wire) -------------------------------------------

Value to_wire(const Obj& obj) {
  Value w = Value::make_map();
  w.set("o", Value::of_bytes(obj.o));
  w.set("a", Value::of_bytes(obj.a));
  if (obj.receipt()) w.set("m", Value::of_bytes(obj.m));
  else w.set("b", Value::of_text(obj.b));
  w.set("t", Value::of_uint(obj.t));
  w.set("s", Value::of_bytes(obj.s));
  if (obj.v.compare(0, 3, "dm:") == 0) {
    auto p = parties(obj.u, obj.v);  // [author, a, b]
    w.set("p", Value::of_text(p.size() == 3 && p[1] == lower(obj.u) ? p[2] : p.size() == 3 ? p[1] : ""));
  } else {
    w.set("v", Value::of_text(obj.v));
  }
  return w;
}

bool from_wire(const Value& w, ObjectSet& set, Obj& obj) {
  obj.a = w.bytes("a");
  obj.u = set.owner_of(obj.a);
  if (obj.u.empty()) return false;
  obj.o = w.bytes("o");
  obj.b = w.text("b");
  obj.m = w.bytes("m");
  obj.t = w.uint("t");
  obj.s = w.bytes("s");
  std::string v = w.text("v");
  obj.v = v.empty() ? dm_id(obj.u, w.text("p")) : v;
  return obj.o.size() == 16 && obj.s.size() == 64 && (obj.m.empty() || obj.m.size() == 16);
}

// -- responder --------------------------------------------------------------------------

bool respond(ObjectSet& set, const char* role, const std::string& op, const Value& p, Value& out) {
  if (op == "HELLO") {
    auto mine = set.interests();
    out = Value::make_map();
    out.set("r", Value::of_text(role));
    out.set("i", string_list(mine));
    out.set("h", string_list(set.held_scopes(mine)));
    return true;
  }
  if (op == "SUM") {
    out = summarize(set.oids(p.text("q")), lower(p.text("p")));
    return true;
  }
  if (op == "WANT") {
    Obj obj{};
    if (set.get(p.bytes("o"), obj)) {
      out = to_wire(obj);
    } else {
      out = Value::make_map();
      out.set("missing", Value::of_bool(true));
    }
    return true;
  }
  if (op == "PUT") {
    Obj obj{};
    if (!from_wire(p, set, obj)) {
      out = error("unknown_identity");
      return false;
    }
    bool created = false;
    std::string err = set.put(obj, created);
    if (!err.empty()) {
      out = error(err);
      return false;
    }
    out = Value::make_map();
    out.set("ok", Value::of_bool(true));
    out.set("new", Value::of_bool(created));
    return true;
  }
  out = error("unknown_op:" + op);
  return false;
}

// -- initiator ----------------------------------------------------------------------------

namespace {

struct Session {
  ObjectSet& set;
  const Ask& ask_fn;
  Result res;
  std::vector<std::string> mine, theirs;
  std::vector<std::string> pull, push;

  Session(ObjectSet& s, const Ask& a) : set(s), ask_fn(a) {}

  bool ask(const char* op, const Value& payload, Reply& out) {
    res.requests++;
    if (ask_fn(op, payload, out)) return true;
    res.ok = false;
    return false;
  }

  bool take_all(const std::vector<std::string>& v) const {
    return std::find(v.begin(), v.end(), "*") != v.end();
  }
  bool pull_ok(const std::string& q) const {
    return take_all(mine) || std::find(mine.begin(), mine.end(), q) != mine.end();
  }
  bool push_ok(const std::string& q) const {
    return take_all(theirs) || std::find(theirs.begin(), theirs.end(), q) != theirs.end();
  }

  bool walk(const std::string& scope, const std::string& prefix) {
    auto have = under(set.oids(scope), prefix);
    Value q = Value::make_map();
    q.set("q", Value::of_text(scope));
    q.set("p", Value::of_text(prefix));
    Reply r;
    if (!ask("SUM", q, r) || !r.error.empty()) return false;
    const Value& p = r.payload();
    if (p.uint("n") == have.size() && p.bytes("x") == fingerprint(have)) return true;
    const Value* list = p.get("oids");
    if (list && list->type == Value::Array) {
      std::vector<std::string> there;
      for (const auto& i : list->items) there.push_back(i.s);
      for (const auto& o : there)
        if (pull_ok(scope) && std::find(have.begin(), have.end(), o) == have.end()) add_unique(pull, o);
      for (const auto& o : have)
        if (push_ok(scope) && std::find(there.begin(), there.end(), o) == there.end()) add_unique(push, o);
      return true;
    }
    const Value* sub = p.get("sub");
    if (!sub || sub->type != Value::Array || sub->items.size() != 16) return false;
    for (int d = 0; d < 16; d++) {
      const Value& pair = sub->items[d];
      if (pair.type != Value::Array || pair.items.size() != 2) return false;
      std::string child_prefix = prefix + "0123456789abcdef"[d];
      auto child = under(have, child_prefix);
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

}  // namespace

Result sync_with(ObjectSet& set, const char* role, const std::string& reply_dest, const Ask& ask) {
  Session s(set, ask);
  s.mine = set.interests();

  Value hello = Value::make_map();
  hello.set("r", Value::of_text(role));
  hello.set("i", string_list(s.mine));
  hello.set("h", string_list(set.held_scopes(s.mine)));
  if (reply_dest.size() == 16) hello.set("rd", Value::of_bytes(reply_dest));
  Reply r;
  if (!s.ask("HELLO", hello, r) || !r.error.empty()) return s.res;
  s.theirs = strings_of(r.payload().get("i"));
  auto their_held = strings_of(r.payload().get("h"));

  // Scopes to reconcile: what either side wants or holds, made concrete;
  // "*" is walked only between two take-everything nodes.
  std::vector<std::string> scopes;
  if (s.take_all(s.mine) && s.take_all(s.theirs)) {
    scopes.push_back("*");
  } else {
    for (const auto* v : {&s.mine, &s.theirs, &their_held})
      for (const auto& q : *v)
        if (q != "*" && (s.pull_ok(q) || s.push_ok(q))) add_unique(scopes, q);
    for (const auto& q : set.held_scopes(s.mine))
      if (s.pull_ok(q) || s.push_ok(q)) add_unique(scopes, q);
  }
  for (const auto& q : scopes)
    if (!s.walk(q, "")) return s.res;

  for (const auto& oid : s.pull) {
    Value q = Value::make_map();
    q.set("o", Value::of_bytes(oid));
    Reply w;
    if (!s.ask("WANT", q, w)) return s.res;
    if (!w.error.empty() || w.payload().flag("missing")) continue;
    Obj obj{};
    if (!from_wire(w.payload(), set, obj)) {
      s.res.rejected++;
      continue;
    }
    if (!s.take_all(s.mine) && !wants(s.mine, obj.u, obj.v)) continue;
    bool created = false;
    std::string err = set.put(obj, created);
    if (!err.empty()) {
      Serial.printf("sync: refused %s: %s\n", hex(oid).substr(0, 8).c_str(), err.c_str());
      s.res.rejected++;
    } else if (created) {
      s.res.pulled++;
    }
  }

  for (const auto& oid : s.push) {
    Obj obj{};
    if (!set.get(oid, obj) || !(s.take_all(s.theirs) || wants(s.theirs, obj.u, obj.v))) continue;
    Reply w;
    if (!s.ask("PUT", to_wire(obj), w)) return s.res;
    if (!w.error.empty()) {
      Serial.printf("sync: peer refused %s: %s\n", hex(oid).substr(0, 8).c_str(), w.error.c_str());
      s.res.rejected++;
      continue;
    }
    set.handed_over(oid);
    if (w.payload().flag("new")) s.res.pushed++;
  }
  return s.res;
}

size_t largest_sync_packet(const std::string& author, const std::string& conv, size_t body_len) {
  Obj probe{};
  probe.o.assign(16, '\0');
  probe.a.assign(16, '\0');
  probe.s.assign(64, '\0');
  probe.t = 4000000000ULL;
  probe.u = author;
  probe.v = conv;
  probe.b.assign(body_len, 'x');
  Value wire = to_wire(probe);
  const char* node = "pocket-1-xxxx";  // the longest node ids
  size_t put = waylink::encode_envelope(node, node, "0123456789abcdef", "0123456789abcdef", "SYNC", "PUT", 1,
                                        120, 4000000000ULL, wire).size();
  size_t want = waylink::encode_envelope(node, node, "0123456789abcdef", "0123456789abcdef", "SYNC", "WANT", 2,
                                         120, 4000000000ULL, wire).size();
  return put > want ? put : want;
}

size_t max_signed_body(const std::string& author, const std::string& conv) {
  const char* node = "pocket-1-xxxx";
  std::vector<waylink::Field> f;
  for (size_t n = 140; n > 0; n--) {
    f.clear();
    if (conv.compare(0, 3, "dm:") == 0) {
      auto p = parties(author, conv);
      f.push_back(waylink::Field::text("p", p.size() == 3 && p[1] == lower(author) ? p[2] : p.size() == 3 ? p[1] : ""));
    } else {
      f.push_back(waylink::Field::text("v", conv));
    }
    f.push_back(waylink::Field::text("b", std::string(n, 'x')));
    f.push_back(waylink::Field::bytes("o", std::string(16, '\0')));
    f.push_back(waylink::Field::bytes("a", std::string(16, '\0')));
    f.push_back(waylink::Field::bytes("s", std::string(64, '\0')));
    size_t send = waylink::encode_request(node, "station", "0123456789abcdef", "0123456789abcdef", "DISPATCH",
                                          "MSG_SEND", 120, f, 4000000000ULL).size();
    if (send <= waylink::kRadioMdu && largest_sync_packet(author, conv, n) <= waylink::kRadioMdu) return n;
  }
  return 0;
}

}  // namespace wp
