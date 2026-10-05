#include "sync.h"

#include <algorithm>
#include <map>
#include <vector>

#include <Arduino.h>

#include "account.h"
#include "app.h"
#include "certs.h"
#include "contacts.h"
#include "station_link.h"
#include "store.h"
#include "wp_objects.h"
#include "wp_sync.h"

namespace peersync {
namespace {

using waylink::Value;

const uint32_t kStationEveryMs = 3UL * 60UL * 1000UL;
const uint32_t kPeerEveryMs = 60UL * 1000UL;  // Outposts and Scouts in range: chat-paced

// The Scout's objects for the shared engine (firmware/common/waypost_core):
// the signed messages in its store, plus signed messages still in its
// outbox — so with Station out of reach they leave through whoever is in
// range (an Outpost, another Scout).
class ScoutSet : public wp::ObjectSet {
 public:
  std::vector<std::string> interests() override {
    std::vector<std::string> out{"u:" + wp::lower(account::username())};
    for (const auto& c : store::conversations())
      if (c.id.compare(0, 5, "room:") == 0) out.push_back("c:" + c.id);
    return out;
  }

  std::vector<wp::Ref> refs() override {
    std::vector<wp::Ref> out;
    for (const auto& r : store::signed_refs()) out.push_back({r.oid, r.author, r.conv});
    for (const auto& o : store::outbox())
      if (!o.sig.empty()) out.push_back({wp::unhex(o.id), account::username(), o.conv});
    return out;
  }

  bool get(const std::string& oid, wp::Obj& out) override {
    std::string id = wp::hex(oid);
    for (const auto& o : store::outbox()) {
      if (o.id != id || o.sig.empty()) continue;
      out = {oid, account::username(), o.author_id, o.conv, o.body, o.sig, o.signed_t};
      return true;
    }
    std::string conv;
    store::Message m;
    if (!store::find_signed(oid, conv, m)) return false;
    out = {oid, m.sender, m.author_id, conv, m.body, m.sig, m.signed_t};
    return true;
  }

  std::string put(const wp::Obj& obj, bool& created) override {
    created = false;
    std::string err = certs::verify_dispatch(obj.o, obj.u, obj.a, obj.v, obj.b, obj.t, obj.s);
    if (!err.empty()) return err;
    store::Message m;
    m.id = wp::hex(obj.o);
    m.sender = obj.u;
    m.body = obj.b;
    uint64_t now = station_link::now_ms();
    m.ts = now ? now : obj.t * 1000ULL;
    m.state = wp::lower(obj.u) == wp::lower(account::username()) ? 's' : 'r';
    m.sig = obj.s;
    m.author_id = obj.a;
    m.signed_t = obj.t;
    created = apps::deliver_message(obj.v, m);
    return "";
  }

  std::string owner_of(const std::string& id) override { return certs::owner_of(id); }

  void handed_over(const std::string& oid) override { store::outbox_passed_on(wp::hex(oid)); }
};

ScoutSet g_set;
std::map<std::string, RNS::Bytes> g_reply_to;  // peer node id -> its destination (from HELLO rd)
uint32_t g_station_at = 0;
std::map<std::string, uint32_t> g_peer_at;  // peer destination hex -> last sync millis
bool g_hurry = false;                      // something just written: sync with peers now

std::string my_dest() { return wp::unhex(station_link::dest_hex()); }

void reply(const waylink::Reply& req, const RNS::Bytes& to, const Value& payload, bool ok) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  RNS::Bytes bytes = waylink::encode_envelope(station_link::node_id().c_str(), src.c_str(),
                                              waylink::new_hex_id(), req.rid, "SYNC", op.c_str(),
                                              ok ? 2 : 2 | 4, 120, 0, payload);
  if (bytes.size() > waylink::kRadioMdu) Serial.printf("sync: %s reply too big (%u)\n", op.c_str(), bytes.size());
  station_link::send_to(to, bytes);
}

bool due(uint32_t at, uint32_t every) { return at == 0 || millis() - at >= every; }

}  // namespace

Result with(const RNS::Bytes& dest, const std::string& node) {
  if (!account::paired() || !store::files_safe()) {
    Result r;
    r.ok = false;
    return r;
  }
  wp::Ask ask = [&](const char* op, const Value& payload, waylink::Reply& out) {
    auto r = station_link::request_peer(dest, node.c_str(), "SYNC", op, payload, out);
    return r == station_link::Result::Ok || r == station_link::Result::Error;
  };
  wp::Result w = wp::sync_with(g_set, "scout", my_dest(), ask);
  Result r;
  r.ok = w.ok;
  r.pulled = w.pulled;
  r.pushed = w.pushed;
  r.rejected = w.rejected;
  r.requests = w.requests;
  return r;
}

void handle(const waylink::Reply& req) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  const Value& p = req.payload();
  if (op == "HELLO") {
    std::string rd = p.bytes("rd");
    if (rd.size() == 16) g_reply_to[src] = wp::bytes(rd);
  }
  RNS::Bytes to;
  if (src == station_link::kStationNodeId) to = station_link::station_dest();
  else if (g_reply_to.count(src)) to = g_reply_to[src];
  if (to.size() != 16) {
    Serial.printf("sync: %s from %s, but no way to reply (no HELLO)\n", op.c_str(), src.c_str());
    return;
  }
  Value out;
  if (!account::paired() || !store::files_safe()) {
    out = Value::make_map();
    out.set("error", Value::of_text("not_ready"));
    reply(req, to, out, false);
    return;
  }
  bool ok = wp::respond(g_set, "scout", op, p, out);
  if (!ok) Serial.printf("sync: refused %s from %s: %s\n", op.c_str(), src.c_str(), out.text("error").c_str());
  reply(req, to, out, ok);
}

size_t largest_packet(const std::string& conv, const std::string& /*peer*/, size_t body_len) {
  return wp::largest_sync_packet(account::username(), conv, body_len);
}

void hurry() { g_hurry = true; }

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
  // Peers in range: Outposts heard announcing, contacts' Scouts with a
  // known path. Every minute, or at once when something was just written.
  std::vector<std::pair<std::string, std::string>> peers;  // (dest hex, node label)
  for (const auto& d : station_link::outposts_heard()) peers.push_back({d, "outpost"});
  for (const auto& c : contacts::all())
    if (c.scout_dest.size() == 32) peers.push_back({c.scout_dest, "scout:" + c.username});
  bool hurry = g_hurry;
  g_hurry = false;
  for (const auto& p : peers) {
    RNS::Bytes dest;
    dest.assignHex(p.first.c_str());
    if (!station_link::has_path(dest)) continue;
    if (!hurry && !due(g_peer_at[p.first], kPeerEveryMs)) continue;
    g_peer_at[p.first] = millis() | 1;
    Result r = with(dest, p.second);
    Serial.printf("sync: %s %s, %d request(s), pulled %d, pushed %d, refused %d\n", p.second.c_str(),
                  r.ok ? "done" : "interrupted", r.requests, r.pulled, r.pushed, r.rejected);
    if (!hurry) return;  // one peer per loop, unless a message is waiting to go
  }
}

}  // namespace peersync
