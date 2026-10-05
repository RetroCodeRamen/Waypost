#include "outpost_objects.h"

#include <algorithm>
#include <map>

#include <Arduino.h>
#include <LittleFS.h>
#include <microReticulum.h>

#include "outpost_net.h"

namespace oobj {
namespace {

using waylink::Value;

const char* const kObjsPath = "/wp_objs";    // one signed message per line
const char* const kCertsPath = "/wp_certs";  // CertCache::serialize
const size_t kKeep = 300;                    // newest kept after a compaction
const size_t kCompactAt = 400;
const uint32_t kStationEveryMs = 2UL * 60UL * 1000UL;
const uint32_t kCertsEveryMs = 30UL * 60UL * 1000UL;
const uint32_t kScoutFreshMs = 30UL * 60UL * 1000UL;  // a Scout that synced this recently is "nearby"
const uint64_t kRenewBeforeS = 7ULL * 24 * 3600;

uint64_t clock_s() { return onet::now_s(); }
wp::CertCache g_cache(&clock_s);
bool g_certs_dirty = false;

struct Entry {
  std::string oid, author, a, conv;
  uint64_t t;
};
std::vector<Entry> g_index;
size_t g_lines = 0;

// People whose Scouts synced with this Outpost lately: user -> (dest, when).
struct Nearby {
  RNS::Bytes dest;
  std::string node;
  uint32_t at;
};
std::map<std::string, Nearby> g_nearby;
std::map<std::string, RNS::Bytes> g_reply_to;  // node -> destination (HELLO rd)
std::vector<std::string> g_push;                // users with something new to push to
std::vector<std::string> g_unknown_ids;         // authors to look up from Station
bool g_station_soon = false;

uint32_t g_station_at = 0, g_certs_at = 0, g_revs_at = 0;

std::string line_of(const wp::Obj& o) {
  return wp::hex(o.o) + "\t" + wp::escape(o.u) + "\t" + wp::hex(o.a) + "\t" + wp::escape(o.v) + "\t" +
         wp::escape(o.b) + "\t" + wp::hex(o.s) + "\t" + std::to_string(o.t) + "\n";
}

bool parse(const std::string& line, wp::Obj& o) {
  auto f = wp::split_tabs(line);
  if (f.size() < 7) return false;
  o = wp::Obj{wp::unhex(f[0]), wp::unescape(f[1]), wp::unhex(f[2]), wp::unescape(f[3]), wp::unescape(f[4]),
              wp::unhex(f[5]), strtoull(f[6].c_str(), nullptr, 10)};
  return o.o.size() == 16;
}

template <typename F>
void each_stored(F fn) {
  File f = LittleFS.open(kObjsPath, FILE_READ);
  if (!f) return;
  while (f.available()) {
    String line = f.readStringUntil('\n');
    wp::Obj o{};
    if (parse(std::string(line.c_str()), o) && !fn(o)) break;
  }
  f.close();
}

void compact() {
  // Keep the newest kKeep (by signed time), rewrite the file.
  std::vector<wp::Obj> all;
  each_stored([&](const wp::Obj& o) {
    all.push_back(o);
    return true;
  });
  std::stable_sort(all.begin(), all.end(), [](const wp::Obj& x, const wp::Obj& y) { return x.t < y.t; });
  if (all.size() > kKeep) all.erase(all.begin(), all.end() - kKeep);
  File f = LittleFS.open(kObjsPath, FILE_WRITE);
  for (const auto& o : all) f.print(line_of(o).c_str());
  f.close();
  g_index.clear();
  for (const auto& o : all) g_index.push_back({o.o, o.u, o.a, o.v, o.t});
  g_lines = all.size();
  Serial.printf("objects: compacted to %u\n", static_cast<unsigned>(g_lines));
}

bool have(const std::string& oid) {
  return std::any_of(g_index.begin(), g_index.end(), [&](const Entry& e) { return e.oid == oid; });
}

void keep(const wp::Obj& o) {
  File f = LittleFS.open(kObjsPath, FILE_APPEND);
  f.print(line_of(o).c_str());
  f.close();
  g_index.push_back({o.o, o.u, o.a, o.v, o.t});
  if (++g_lines >= kCompactAt) compact();
  // Deliver: everyone it concerns whose Scout is nearby gets it pushed now;
  // Station gets it at the next chance.
  for (const auto& p : wp::parties(o.u, o.v))
    if (std::find(g_push.begin(), g_push.end(), p) == g_push.end()) g_push.push_back(p);
  g_station_soon = true;
}

class OutpostSet : public wp::ObjectSet {
 public:
  std::vector<std::string> interests() override { return {"*"}; }

  std::vector<wp::Ref> refs() override {
    std::vector<wp::Ref> out;
    out.reserve(g_index.size());
    for (const auto& e : g_index) out.push_back({e.oid, e.author, e.conv});
    return out;
  }

  bool get(const std::string& oid, wp::Obj& out) override {
    if (!have(oid)) return false;
    bool found = false;
    each_stored([&](const wp::Obj& o) {
      if (o.o != oid) return true;
      out = o;
      found = true;
      return false;
    });
    return found;
  }

  std::string put(const wp::Obj& obj, bool& created) override {
    created = false;
    if (have(obj.o)) return "";
    std::string err = g_cache.verify_dispatch(obj.o, obj.u, obj.a, obj.v, obj.b, obj.t, obj.s);
    if (!err.empty()) return err;
    keep(obj);
    created = true;
    return "";
  }

  std::string owner_of(const std::string& id) override {
    std::string who = g_cache.owner_of(id);
    if (who.empty() && id.size() == 16 && g_unknown_ids.size() < 16 &&
        std::find(g_unknown_ids.begin(), g_unknown_ids.end(), id) == g_unknown_ids.end())
      g_unknown_ids.push_back(id);
    return who;
  }
};

OutpostSet g_set;

bool ask_station(const char* svc, const char* op, const Value& payload, waylink::Reply& out) {
  return onet::request(onet::station_dest(), "station", svc, op, payload, out);
}

void save_certs() {
  RNS::Utilities::OS::write_file(kCertsPath, RNS::Bytes(g_cache.serialize("outpost")));
}

void add_cert(const waylink::Value* v) {
  wp::Cert c;
  if (v && wp::from_value(*v, c) && g_cache.add(c)) g_certs_dirty = true;
}

bool station_ready() {
  RNS::Bytes s = onet::station_dest();
  return s.size() == 16 && onet::has_path(s) && !onet::station_quiet();
}

// One step of certificate upkeep with Station. False when nothing was due.
bool certs_step() {
  waylink::Reply r;
  if (g_cache.root.empty()) {
    if (ask_station("PROFILE", "CERT_ROOT", Value::make_map(), r) && g_cache.offer_root(r.payload().bytes("pk"))) {
      g_certs_dirty = true;
      Serial.println("objects: community key pinned");
    }
    return true;
  }
  if (!g_unknown_ids.empty()) {
    std::string id = g_unknown_ids.back();
    g_unknown_ids.pop_back();
    Value q = Value::make_map();
    q.set("i", Value::of_bytes(id));
    if (ask_station("PROFILE", "CERT_GET", q, r) && r.error.empty()) add_cert(r.payload().get("cert"));
    return true;
  }
  if (!g_certs_at || millis() - g_certs_at > kCertsEveryMs) {
    uint64_t offset = 0;
    for (int page = 0; page < 30; page++) {
      Value q = Value::make_map();
      q.set("offset", Value::of_uint(offset));
      if (!ask_station("PROFILE", "CERT_LIST", q, r) || !r.error.empty()) {
        // Not marked done: tried again at the next step Station is in reach.
        Serial.printf("objects: CERT_LIST failed (%s)\n", r.error.empty() ? "no answer" : r.error.c_str());
        return true;
      }
      const Value* list = r.payload().get("certs");
      size_t n = 0;
      if (list && list->type == Value::Array)
        for (const auto& c : list->items) {
          add_cert(&c);
          n++;
        }
      offset += n;
      if (!r.payload().flag("more") || n == 0) break;
    }
    g_certs_at = millis() | 1;
    Serial.printf("objects: %u certificate(s) cached\n", static_cast<unsigned>(g_cache.certs.size()));
    return true;
  }
  if (!g_revs_at || millis() - g_revs_at > kCertsEveryMs) {
    g_revs_at = millis() | 1;
    Value q = Value::make_map();
    q.set("offset", Value::of_uint(0));
    if (ask_station("PROFILE", "CERT_REVOKED", q, r) && r.error.empty()) {
      const Value* list = r.payload().get("revs");
      if (list && list->type == Value::Array)
        for (const auto& c : list->items) add_cert(&c);
    }
    return true;
  }
  return false;
}

wp::Result sync_with(const RNS::Bytes& dest, const std::string& node) {
  wp::Ask ask = [&](const char* op, const Value& payload, waylink::Reply& out) {
    return onet::request(dest, node.c_str(), "SYNC", op, payload, out);
  };
  return wp::sync_with(g_set, "outpost", onet::self_dest(), ask);
}

void reply(const waylink::Reply& req, const RNS::Bytes& to, const Value& payload, bool ok, const std::string& self) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  onet::send_to(to, waylink::encode_envelope(self.c_str(), src.c_str(), waylink::new_hex_id(), req.rid, "SYNC",
                                             op.c_str(), ok ? 2 : 2 | 4, 120, 0, payload));
}

std::string g_self_node = "outpost";

}  // namespace

wp::CertCache& certs() { return g_cache; }
size_t count() { return g_index.size(); }

void load() {
  {
    std::vector<std::string> lines;
    File f = LittleFS.open(kCertsPath, FILE_READ);
    if (f) {
      while (f.available()) lines.push_back(std::string(f.readStringUntil('\n').c_str()));
      f.close();
    }
    g_cache.load(lines, "outpost");
  }
  g_index.clear();
  g_lines = 0;
  each_stored([&](const wp::Obj& o) {
    if (!have(o.o)) g_index.push_back({o.o, o.u, o.a, o.v, o.t});
    g_lines++;
    return true;
  });
  Serial.printf("objects: %u message(s), %u certificate(s), community key %s, self-test %s\n",
                static_cast<unsigned>(g_index.size()), static_cast<unsigned>(g_cache.certs.size()),
                g_cache.root.empty() ? "not yet" : "pinned", wp::self_test() ? "ok" : "FAILED");
}

void set_self_node(const std::string& node) { g_self_node = node; }

void handle_request(const waylink::Reply& req) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  const Value& p = req.payload();
  if (op == "HELLO") {
    std::string rd = p.bytes("rd");
    if (rd.size() == 16) {
      g_reply_to[src] = wp::bytes(rd);
      // A Scout syncing with us is nearby: remember where its person is.
      const Value* interests = p.get("i");
      if (interests && interests->type == Value::Array)
        for (const auto& q : interests->items)
          if (q.type == Value::Text && q.s.compare(0, 2, "u:") == 0)
            g_nearby[wp::lower(q.s.substr(2))] = {wp::bytes(rd), src, millis()};
    }
  }
  RNS::Bytes to;
  if (src == "station") to = onet::station_dest();
  else if (g_reply_to.count(src)) to = g_reply_to[src];
  if (to.size() != 16) {
    Serial.printf("sync: %s from %s, but no way to reply (no HELLO)\n", op.c_str(), src.c_str());
    return;
  }
  Value out;
  bool ok = wp::respond(g_set, "outpost", op, p, out);
  if (!ok) Serial.printf("sync: refused %s from %s: %s\n", op.c_str(), src.c_str(), out.text("error").c_str());
  reply(req, to, out, ok, g_self_node);
}

void loop() {
  if (g_certs_dirty) {
    g_certs_dirty = false;
    save_certs();
  }
  // Someone nearby has something new: push it to their Scout first (chat).
  while (!g_push.empty()) {
    std::string user = g_push.back();
    g_push.pop_back();
    auto it = g_nearby.find(user);
    if (it == g_nearby.end() || millis() - it->second.at > kScoutFreshMs) continue;
    wp::Result r = sync_with(it->second.dest, it->second.node);
    Serial.printf("sync: pushed to %s's Scout: %s, %d request(s), pushed %d\n", user.c_str(),
                  r.ok ? "done" : "no answer", r.requests, r.pushed);
    return;
  }
  if (!station_ready()) return;
  static uint32_t step_at = 0;
  if (step_at && millis() - step_at < 1500) return;
  step_at = millis();
  if (certs_step()) return;
  if (g_station_soon || !g_station_at || millis() - g_station_at > kStationEveryMs) {
    g_station_soon = false;
    g_station_at = millis() | 1;
    wp::Result r = sync_with(onet::station_dest(), "station");
    Serial.printf("sync: Station %s, %d request(s), pulled %d, pushed %d, refused %d\n",
                  r.ok ? "done" : "interrupted", r.requests, r.pulled, r.pushed, r.rejected);
  }
}

std::vector<Conversation> conversations_for(const std::string& user) {
  std::map<std::string, Conversation> by_id;
  std::string me = wp::lower(user);
  for (const auto& e : g_index) {
    if (!wp::in_scope("u:" + me, e.author, e.conv)) continue;
    Conversation& c = by_id[e.conv];
    c.id = e.conv;
    auto p = wp::parties(e.author, e.conv);
    if (p.size() == 3) c.with = p[1] == me ? p[2] : p[1];
    c.count++;
    if (e.t >= c.last_t) c.last_t = e.t;
  }
  std::vector<Conversation> out;
  for (auto& kv : by_id) out.push_back(kv.second);
  std::sort(out.begin(), out.end(), [](const Conversation& a, const Conversation& b) { return a.last_t > b.last_t; });
  return out;
}

std::vector<wp::Obj> messages(const std::string& conv, size_t max) {
  std::vector<wp::Obj> out;
  each_stored([&](const wp::Obj& o) {
    if (o.v == conv) out.push_back(o);
    return true;
  });
  std::stable_sort(out.begin(), out.end(), [](const wp::Obj& x, const wp::Obj& y) { return x.t < y.t; });
  if (out.size() > max) out.erase(out.begin(), out.end() - max);
  return out;
}

std::string add_local(const wp::Obj& obj) {
  if (have(obj.o)) return "";
  keep(obj);
  return "";
}

bool vouched(const std::string& username, const std::string& public_key) {
  const wp::Cert* c = g_cache.identity(username);
  return c && c->p == public_key;
}

}  // namespace oobj
