#include "station_link.h"

#include <cstring>
#include <deque>

#include <Arduino.h>

#include <microStore/FileSystem.h>
#include <microStore/Adapters/LittleFSFileSystem.h>
#include <LoRaInterface.h>
#include <microReticulum.h>

#ifndef WAYPOST_POCKET_ID
#define WAYPOST_POCKET_ID "pocket-1"
#endif
#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif

namespace station_link {

const char* const kStationNodeId = "station";

namespace {

const char* const kAppName = "waypost";
const char* const kAspect = "waylink";
const char* const kIdentityPath = "/waypost_identity";
const uint32_t kReannounceMs = 10UL * 60UL * 1000UL;
const uint32_t kPathWaitMs = 12000;

RNS::Reticulum g_reticulum({RNS::Type::NONE});
RNS::Interface g_lora_interface({RNS::Type::NONE});
RNS::Identity g_identity({RNS::Type::NONE});
RNS::Destination g_destination({RNS::Type::NONE});

std::string g_node_id = WAYPOST_POCKET_ID;
std::string g_dest_hex;

// Reply matching: the callback only accepts a reply whose rid is the one
// currently being waited for, so a late reply to an abandoned attempt
// can't be mistaken for the current one.
std::string g_waiting_rid;
bool g_reply_ready = false;
waylink::Reply g_reply;

std::deque<waylink::IncomingChatMessage> g_incoming;

void (*g_busy_tick)() = nullptr;
void (*g_busy_done)() = nullptr;

void busy_tick() {
  if (g_busy_tick) g_busy_tick();
}
void busy_done() {
  if (g_busy_done) g_busy_done();
}

// Runs inside g_reticulum.loop() on the same thread as Arduino loop(), so
// no locking. Never sends from here (no reentrant sends into Reticulum).
void on_packet(const RNS::Bytes& data, const RNS::Packet& /*packet*/) {
  waylink::IncomingChatMessage msg;
  if (waylink::decode_msg_push(data.data(), data.size(), msg)) {
    if (g_incoming.size() < 16) g_incoming.push_back(std::move(msg));
    return;
  }
  waylink::Reply reply;
  if (!waylink::parse_reply(data.data(), data.size(), reply)) {
    Serial.println("link: undecodable packet dropped");
    return;
  }
  if (g_waiting_rid.empty() || reply.rid != g_waiting_rid) {
    Serial.printf("link: stale reply rid=%s dropped\n", reply.rid.c_str());
    return;
  }
  g_reply = std::move(reply);
  g_reply_ready = true;
}

bool station_hash(RNS::Bytes& out) {
  static const char* hex = WAYPOST_STATION_DEST_HASH;
  if (strlen(hex) != 32) return false;
  out.assignHex(hex);
  return out.size() == 16;
}

// Resolves Station's path + identity, requesting a path if needed.
bool connect(RNS::Destination& out) {
  RNS::Bytes hash;
  if (!station_hash(hash)) {
    Serial.println("link: WAYPOST_STATION_DEST_HASH not set");
    return false;
  }
  if (!RNS::Transport::has_path(hash)) {
    RNS::Transport::request_path(hash);
    uint32_t start = millis();
    while (!RNS::Transport::has_path(hash) && millis() - start < kPathWaitMs) {
      g_reticulum.loop();
      busy_tick();
      delay(20);
    }
    if (!RNS::Transport::has_path(hash)) return false;
  }
  RNS::Identity identity = RNS::Identity::recall(hash);
  if (!identity) return false;
  out = RNS::Destination(identity, RNS::Type::Destination::OUT,
                         RNS::Type::Destination::SINGLE, kAppName, kAspect);
  return true;
}

}  // namespace

void set_busy_hooks(void (*tick)(), void (*done)()) {
  g_busy_tick = tick;
  g_busy_done = done;
}

bool setup(Progress progress) {
  auto step = [&](const char* label, int pct) {
    Serial.printf("boot: %s\n", label);
    if (progress) progress(label, pct);
  };
  step("Mounting storage", 10);
  static microStore::FileSystem filesystem{microStore::Adapters::LittleFSFileSystem()};
  filesystem.init(false);
  RNS::Utilities::OS::register_filesystem(filesystem);
  // microReticulum persistence stores — absolute paths, must exist first
  // (relative paths are silently rejected by ESP32's LittleFS VFS).
  filesystem.mkdir("/rns");
  filesystem.mkdir("/cache");
  filesystem.mkdir("/path_store");
  filesystem.mkdir("/known_store");
  filesystem.mkdir("/hashlist_store");

  step("Starting LoRa radio", 30);
  g_lora_interface = new LoRaInterface();
  g_lora_interface.mode(RNS::Type::Interface::MODE_GATEWAY);
  RNS::Transport::register_interface(g_lora_interface);
  if (!g_lora_interface.start()) {
    Serial.println("link: LoRa init failed");
    return false;
  }

  step("Starting Reticulum", 50);
  g_reticulum = RNS::Reticulum();
  RNS::Reticulum::storagepath("/rns");
  g_reticulum.transport_enabled(true);
  // No probe-responder destination: nothing probes a Scout (Station doesn't;
  // neighbor probing is off below), and its announces — plus Station's
  // rebroadcasts of them — doubled the burst of traffic right after boot,
  // exactly when the Scout's first request goes out.
  g_reticulum.probe_destination_enabled(false);
  // Neighbor probing is for relay nodes. Station (Python RNS) never sends
  // proofs for Waylink packets, so after 5 sends microReticulum flags it
  // "suspicious" and retries a probe every jobs() tick (log spam), and a
  // probe that did time out would demote Station's paths to UNRESPONSIVE.
  RNS::Reticulum::neighbor_probing_enabled(false);
  g_reticulum.start();

  step("Loading identity", 80);
  g_identity = RNS::Identity::from_file(kIdentityPath);
  if (!g_identity) {
    Serial.println("No saved identity — generating a new one");
    g_identity = RNS::Identity();
    g_identity.to_file(kIdentityPath);
  } else {
    Serial.println("Loaded saved identity from flash");
  }

  g_destination = RNS::Destination(g_identity, RNS::Type::Destination::IN,
                                   RNS::Type::Destination::SINGLE, kAppName, kAspect);
  g_destination.set_packet_callback(on_packet);

  g_dest_hex = g_destination.hash().toHex();
  g_node_id = std::string(WAYPOST_POCKET_ID) + "-" + g_dest_hex.substr(0, 4);
  step("Announcing", 95);
  g_destination.announce();

  Serial.printf("Scout Reticulum destination: %s\n", g_dest_hex.c_str());
  Serial.printf("device_class=pocket node_id=%s\n", g_node_id.c_str());
  return true;
}

void loop() {
  g_reticulum.loop();
  static uint32_t last_announce = millis();
  if (millis() - last_announce >= kReannounceMs) {
    if (g_destination) g_destination.announce();
    last_announce = millis();
  }
}

const std::string& node_id() { return g_node_id; }
const std::string& dest_hex() { return g_dest_hex; }

bool station_known() {
  RNS::Bytes hash;
  return station_hash(hash) && RNS::Transport::has_path(hash) &&
         static_cast<bool>(RNS::Identity::recall(hash));
}

void seek_station() {
  static uint32_t last = 0;
  static bool asked = false;
  if (station_known()) return;
  if (asked && millis() - last < 30000) return;
  RNS::Bytes hash;
  if (!station_hash(hash)) return;
  asked = true;
  last = millis();
  RNS::Transport::request_path(hash);
}

const char* describe(Result r) {
  switch (r) {
    case Result::Ok: return "ok";
    case Result::NoPath: return "no path to Station";
    case Result::Timeout: return "no reply from Station";
    case Result::Error: return "Station returned an error";
  }
  return "?";
}

namespace {
Result request_impl(const Builder& build, waylink::Reply& out, int attempts,
                    uint32_t timeout_ms) {
  RNS::Destination dest({RNS::Type::NONE});
  if (!connect(dest)) return Result::NoPath;

  for (int attempt = 1; attempt <= attempts; attempt++) {
    std::string mid = waylink::new_hex_id();
    std::string rid = waylink::new_hex_id();
    g_waiting_rid = rid;
    g_reply_ready = false;

    RNS::Packet pkt(dest, build(mid, rid));
    pkt.send();

    uint32_t start = millis();
    while (!g_reply_ready && millis() - start < timeout_ms) {
      g_reticulum.loop();
      busy_tick();
      delay(10);
    }
    if (g_reply_ready) {
      g_waiting_rid.clear();
      g_reply_ready = false;
      out = std::move(g_reply);
      if (!out.error.empty()) return Result::Error;
      Serial.printf("link: reply in %lums (attempt %d)\n",
                    static_cast<unsigned long>(millis() - start), attempt);
      return Result::Ok;
    }
    Serial.printf("link: attempt %d/%d timed out\n", attempt, attempts);
  }
  g_waiting_rid.clear();
  return Result::Timeout;
}
}  // namespace

Result request(const Builder& build, waylink::Reply& out, int attempts, uint32_t timeout_ms) {
  busy_tick();
  Result r = request_impl(build, out, attempts, timeout_ms);
  busy_done();
  return r;
}

Result request(const char* svc, const char* op, const std::vector<waylink::Field>& payload,
               waylink::Reply& out, int attempts, uint32_t timeout_ms) {
  return request(
      [&](const std::string& mid, const std::string& rid) {
        return waylink::encode_request(node_id().c_str(), kStationNodeId, mid, rid, svc, op,
                                       120, payload);
      },
      out, attempts, timeout_ms);
}

bool send(const RNS::Bytes& payload) {
  RNS::Destination dest({RNS::Type::NONE});
  if (!connect(dest)) return false;
  RNS::Packet pkt(dest, payload);
  pkt.send();
  return true;
}

bool pop_incoming(waylink::IncomingChatMessage& out) {
  if (g_incoming.empty()) return false;
  out = std::move(g_incoming.front());
  g_incoming.pop_front();
  return true;
}

}  // namespace station_link
