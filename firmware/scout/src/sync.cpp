#include "sync.h"

#include <algorithm>
#include <map>
#include <vector>

#include <Arduino.h>

#include "account.h"
#include "app.h"
#include "certs.h"
#include "contacts.h"
#include "net.h"
#include "receipts.h"
#include "tasks.h"
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
//
// The engine runs on the sync worker (tasks.h) and waits on each reply;
// every touch of the store, certificates or account happens on the UI task
// (on_ui), which owns them.
class ScoutSet : public wp::ObjectSet {
 public:
  std::vector<std::string> interests() override {
    std::vector<std::string> out;
    tasks::on_ui([&] {
      out.push_back("u:" + wp::lower(account::username()));
      for (const auto& c : store::conversations())
        if (c.id.compare(0, 5, "room:") == 0) out.push_back("c:" + c.id);
    });
    return out;
  }

  std::vector<wp::Ref> refs() override {
    std::vector<wp::Ref> out;
    tasks::on_ui([&] {
      for (const auto& r : store::signed_refs()) out.push_back({r.oid, r.author, r.conv});
      for (const auto& o : store::outbox())
        if (!o.sig.empty()) out.push_back({wp::unhex(o.id), account::username(), o.conv});
      for (const auto& r : receipts::all())
        if (!r.sig.empty()) out.push_back({r.oid, r.user, r.conv});
    });
    return out;
  }

  bool get(const std::string& oid, wp::Obj& out) override {
    bool found = false;
    tasks::on_ui([&] {
      std::string id = wp::hex(oid);
      for (const auto& o : store::outbox()) {
        if (o.id != id || o.sig.empty()) continue;
        out = {oid, account::username(), o.author_id, o.conv, o.body, o.sig, o.signed_t};
        found = true;
        return;
      }
      if (const receipts::Receipt* r = receipts::find(oid)) {
        if (r->sig.empty()) return;  // not signed yet: not ready to travel
        out = {r->oid, r->user, r->author_id, r->conv, "", r->sig, r->t, r->m};
        found = true;
        return;
      }
      std::string conv;
      store::Message m;
      if (!store::find_signed(oid, conv, m)) return;
      out = {oid, m.sender, m.author_id, conv, m.body, m.sig, m.signed_t};
      found = true;
    });
    return found;
  }

  std::string put(const wp::Obj& obj, bool& created) override {
    std::string err;
    bool made = false;
    tasks::on_ui([&] {
      if (obj.receipt()) {
        err = certs::verify_receipt(obj.o, obj.u, obj.a, obj.v, obj.m, obj.t, obj.s);
        if (!err.empty()) return;
        made = receipts::add({obj.o, obj.m, obj.v, obj.u, obj.a, obj.s, obj.t});
        if (made) apps::receipt_arrived(obj.v);
        return;
      }
      err = certs::verify_dispatch(obj.o, obj.u, obj.a, obj.v, obj.b, obj.t, obj.s);
      if (!err.empty()) return;
      store::Message m;
      m.id = wp::hex(obj.o);
      m.sender = obj.u;
      m.body = obj.b;
      uint64_t now = net::now_ms();
      m.ts = now ? now : obj.t * 1000ULL;
      m.state = wp::lower(obj.u) == wp::lower(account::username()) ? 's' : 'r';
      m.sig = obj.s;
      m.author_id = obj.a;
      m.signed_t = obj.t;
      made = apps::deliver_message(obj.v, m);
    });
    created = made;
    return err;
  }

  std::string owner_of(const std::string& id) override {
    std::string who;
    tasks::on_ui([&] { who = certs::owner_of(id); });
    return who;
  }

  void handed_over(const std::string& oid) override {
    tasks::on_ui([&] { store::outbox_passed_on(wp::hex(oid)); });
  }
};

ScoutSet g_set;
std::map<std::string, RNS::Bytes> g_reply_to;  // peer node id -> its destination (from HELLO rd)
uint32_t g_station_at = 0;
std::map<std::string, uint32_t> g_peer_at;  // peer destination hex -> last sync millis
bool g_hurry = false;                      // something just written: sync with peers now

std::string my_dest() { return wp::unhex(net::status().dest_hex); }

void reply(const waylink::Reply& req, const RNS::Bytes& to, const Value& payload, bool ok) {
  std::string op = req.envelope.text("op");
  std::string src = req.envelope.text("src");
  RNS::Bytes bytes = waylink::encode_envelope(net::status().node_id.c_str(), src.c_str(),
                                              waylink::new_hex_id(), req.rid, "SYNC", op.c_str(),
                                              ok ? 2 : 2 | 4, 120, 0, payload);
  if (bytes.size() > waylink::kRadioMdu) Serial.printf("sync: %s reply too big (%u)\n", op.c_str(), bytes.size());
  net::send(to, bytes);
}

bool due(uint32_t at, uint32_t every) { return at == 0 || millis() - at >= every; }

}  // namespace

// On the sync worker.
Result with(const RNS::Bytes& dest, const std::string& node) {
  std::string me = my_dest();
  wp::Ask ask = [&](const char* op, const Value& payload, waylink::Reply& out) {
    net::Request req;
    req.dest = dest;
    req.dst_node = node;
    req.svc = "SYNC";
    req.op = op;
    req.tree = payload;
    req.use_tree = true;
    req.attempts = 2;
    auto r = rpc::call(std::move(req), out);
    return r == net::Result::Ok || r == net::Result::Error;
  };
  wp::Result w = wp::sync_with(g_set, "scout", me, ask);
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
  if (src == net::kStationNodeId) to = net::station_dest();
  else if (g_reply_to.count(src)) to = g_reply_to[src];
  if (to.size() != 16) {
    Serial.printf("sync: %s from %s, but no way to reply (no HELLO)\n", op.c_str(), src.c_str());
    return;
  }
  Value out;
  if (!account::paired()) {
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

namespace {

// Starts a sync with one peer on the sync worker.
void start(const RNS::Bytes& dest, const std::string& node, const std::string& label) {
  tasks::run(tasks::Worker::Sync, [dest, node, label] {
    Result r = with(dest, node);
    Serial.printf("sync: %s %s, %d request(s), pulled %d, pushed %d, refused %d\n", label.c_str(),
                  r.ok ? "done" : "interrupted", r.requests, r.pulled, r.pushed, r.rejected);
  });
}

}  // namespace

// UI task. One peer at a time: a new one starts once the worker is idle.
void loop() {
  if (!account::paired() || !net::ready() || !certs::idle()) return;
  if (!tasks::idle(tasks::Worker::Sync)) return;
  // Station: the archive. Catch-up (MSG_SYNC) still covers unsigned messages.
  if (net::station_known() && due(g_station_at, kStationEveryMs)) {
    g_station_at = millis() | 1;
    start(net::station_dest(), net::kStationNodeId, "Station");
    return;
  }
  // Peers in range: Outposts heard announcing, contacts' Scouts with a
  // known path. Every minute, or at once when something was just written.
  std::vector<std::pair<std::string, std::string>> peers;  // (dest hex, node label)
  for (const auto& d : net::status().outposts) peers.push_back({d, "outpost"});
  for (const auto& c : contacts::all())
    if (c.scout_dest.size() == 32) peers.push_back({c.scout_dest, "scout:" + c.username});
  for (const auto& p : peers) {
    // Hurrying: every peer once (not one done in the last few seconds).
    uint32_t at = g_peer_at[p.first];
    if (g_hurry ? (at && millis() - at < 5000) : !due(at, kPeerEveryMs)) continue;
    RNS::Bytes dest;
    dest.assignHex(p.first.c_str());
    g_peer_at[p.first] = millis() | 1;
    if (!net::has_path(dest)) continue;  // not in range: look again next round
    start(dest, p.second, p.second);
    return;
  }
  g_hurry = false;  // every peer had its turn
}

}  // namespace peersync
