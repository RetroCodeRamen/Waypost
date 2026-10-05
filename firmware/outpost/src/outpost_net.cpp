#include "outpost_net.h"

#include <deque>

#include <Arduino.h>

#include "wp_objects.h"

#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif

namespace onet {
namespace {

RNS::Reticulum* g_rns = nullptr;
RNS::Destination* g_self = nullptr;
const std::string* g_node = nullptr;

std::string g_waiting_rid;
bool g_reply_ready = false;
waylink::Reply g_reply;
std::deque<waylink::Reply> g_requests;

uint64_t g_epoch_s = 0;
uint32_t g_epoch_at = 0;
uint32_t g_quiet_until = 0;

bool connect_to(const RNS::Bytes& hash, RNS::Destination& out) {
  if (hash.size() != 16) return false;
  if (!RNS::Transport::has_path(hash)) {
    RNS::Transport::request_path(hash);
    uint32_t start = millis();
    while (!RNS::Transport::has_path(hash) && millis() - start < 8000) {
      g_rns->loop();
      delay(20);
    }
    if (!RNS::Transport::has_path(hash)) return false;
  }
  RNS::Identity identity = RNS::Identity::recall(hash);
  if (!identity) return false;
  out = RNS::Destination(identity, RNS::Type::Destination::OUT, RNS::Type::Destination::SINGLE, "waypost",
                         "waylink");
  return true;
}

}  // namespace

void attach(RNS::Reticulum* reticulum, RNS::Destination* self, const std::string* node_id) {
  g_rns = reticulum;
  g_self = self;
  g_node = node_id;
}

bool on_packet(const RNS::Bytes& data) {
  waylink::Reply reply;
  if (!waylink::parse_reply(data.data(), data.size(), reply)) return false;
  if (reply.envelope.text("src") == "station") {
    g_quiet_until = 0;
    uint64_t ts = reply.envelope.uint("ts");
    if (ts > 1600000000ULL) {
      g_epoch_s = ts;
      g_epoch_at = millis();
    }
  }
  // Flags: REQUEST 1, RESPONSE 2. A peer's request (SYNC from a Scout,
  // another Outpost, Station) is queued for the main loop.
  if ((reply.flags & 1) && !(reply.flags & 2)) {
    if (reply.envelope.text("svc") != "SYNC") return false;  // not ours (e.g. a claim ack)
    if (g_requests.size() < 8) g_requests.push_back(std::move(reply));
    return true;
  }
  if (!g_waiting_rid.empty() && reply.rid == g_waiting_rid) {
    g_reply = std::move(reply);
    g_reply_ready = true;
    return true;
  }
  return false;
}

bool has_path(const RNS::Bytes& dest) { return dest.size() == 16 && RNS::Transport::has_path(dest); }

bool request(const RNS::Bytes& dest, const char* dst_node, const char* svc, const char* op,
             const waylink::Value& payload, waylink::Reply& out, int attempts, uint32_t timeout_ms) {
  if (!g_rns || !g_node) return false;
  RNS::Destination d({RNS::Type::NONE});
  if (!connect_to(dest, d)) return false;
  for (int attempt = 1; attempt <= attempts; attempt++) {
    std::string mid = waylink::new_hex_id(), rid = waylink::new_hex_id();
    g_waiting_rid = rid;
    g_reply_ready = false;
    RNS::Packet pkt(d, waylink::encode_envelope(g_node->c_str(), dst_node, mid, rid, svc, op, 1, 120, 0, payload));
    pkt.send();
    uint32_t start = millis();
    while (!g_reply_ready && millis() - start < timeout_ms) {
      g_rns->loop();
      delay(10);
    }
    if (g_reply_ready) {
      g_waiting_rid.clear();
      g_reply_ready = false;
      out = std::move(g_reply);
      return true;
    }
  }
  g_waiting_rid.clear();
  if (dest == station_dest()) g_quiet_until = (millis() + 120000) | 1;
  return false;
}

bool send_to(const RNS::Bytes& dest, const RNS::Bytes& bytes) {
  RNS::Destination d({RNS::Type::NONE});
  if (!connect_to(dest, d)) return false;
  RNS::Packet pkt(d, bytes);
  pkt.send();
  return true;
}

bool pop_request(waylink::Reply& out) {
  if (g_requests.empty()) return false;
  out = std::move(g_requests.front());
  g_requests.pop_front();
  return true;
}

RNS::Bytes station_dest() {
  RNS::Bytes h;
  static const char* hex = WAYPOST_STATION_DEST_HASH;
  if (strlen(hex) == 32) h.assignHex(hex);
  return h;
}

std::string self_dest() { return g_self ? wp::raw(g_self->hash()) : ""; }

uint64_t now_s() {
  if (!g_epoch_s) return 0;
  return g_epoch_s + (millis() - g_epoch_at) / 1000;
}

bool station_quiet() { return g_quiet_until && static_cast<int32_t>(millis() - g_quiet_until) < 0; }

}  // namespace onet
