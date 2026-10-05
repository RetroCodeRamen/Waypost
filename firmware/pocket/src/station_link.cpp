#include "station_link.h"

#include "spi_bus.h"

#include <algorithm>
#include <atomic>
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
std::deque<waylink::Reply> g_events;  // unsolicited requests (not chat)

// Wall clock learned from Station's envelope ts (seconds); the Scout has no
// RTC. 0 until the first reply.
uint64_t g_epoch_s = 0;
// Station had a path but stopped answering (switched off, out of range):
// treat it as out of reach for a while instead of spending tens of seconds
// per request on timeouts — time in which the Scout can't answer peers.
const uint32_t kQuietMs = 2UL * 60UL * 1000UL;
uint32_t g_station_quiet_until = 0;
bool station_quiet() {
  return g_station_quiet_until && static_cast<int32_t>(millis() - g_station_quiet_until) < 0;
}
uint32_t g_epoch_at_ms = 0;

// Outposts heard announcing (their announce app_data starts with
// WPOST-OUTPOST: or, before they're claimed, WPOST-CLAIM:) — peers to sync
// with when they're in range.
std::vector<std::string> g_outposts;

class OutpostWatcher : public RNS::AnnounceHandler {
 public:
  OutpostWatcher() : RNS::AnnounceHandler("waypost.waylink") {}
  void received_announce(const RNS::Bytes& destination_hash, const RNS::Identity& /*identity*/,
                         const RNS::Bytes& app_data) override {
    std::string ad(reinterpret_cast<const char*>(app_data.data()), app_data.size());
    if (ad.compare(0, 14, "WPOST-OUTPOST:") != 0 && ad.compare(0, 12, "WPOST-CLAIM:") != 0) return;
    std::string hex = destination_hash.toHex();
    if (std::find(g_outposts.begin(), g_outposts.end(), hex) != g_outposts.end()) return;
    if (g_outposts.size() >= 8) g_outposts.erase(g_outposts.begin());
    g_outposts.push_back(hex);
    Serial.printf("link: Outpost heard %s (%s)\n", hex.c_str(), ad.c_str());
  }
};

void (*g_busy_tick)() = nullptr;
void (*g_busy_done)() = nullptr;

void (*g_wait_hook)() = nullptr;

void busy_tick() {
  if (g_busy_tick) g_busy_tick();
  if (g_wait_hook) g_wait_hook();
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
  // Wall clock from Station only: a peer's clock may be wrong, and a sync
  // reply's time is the object's, not now.
  if (reply.envelope.text("src") == kStationNodeId) g_station_quiet_until = 0;  // it's back
  uint64_t ts = reply.envelope.text("src") == kStationNodeId ? reply.envelope.uint("ts") : 0;
  if (ts > 1600000000ULL) {
    g_epoch_s = ts;
    g_epoch_at_ms = millis();
  }
  // A REQUEST that isn't a RESPONSE is Station telling us something
  // unprompted (Flags.REQUEST = 1, RESPONSE = 2).
  if ((reply.flags & 1) && !(reply.flags & 2)) {
    if (g_events.size() < 8) g_events.push_back(std::move(reply));
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

// Resolves a destination's path + identity, requesting a path if needed.
bool connect_to(const RNS::Bytes& hash, RNS::Destination& out) {
  if (hash.size() != 16) return false;
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

bool connect(RNS::Destination& out) {
  RNS::Bytes hash;
  if (!station_hash(hash)) {
    Serial.println("link: WAYPOST_STATION_DEST_HASH not set");
    return false;
  }
  return connect_to(hash, out);
}

}  // namespace

void set_wait_hook(void (*hook)()) { g_wait_hook = hook; }

void set_busy_hooks(void (*tick)(), void (*done)()) {
  g_busy_tick = tick;
  g_busy_done = done;
}

namespace {

// Radio bring-up runs on its own task (start()). g_state is the hand-off:
// the task owns Reticulum until it publishes Ready; the main loop owns it
// after. Boot step times are written only by the task, read only after.
enum State : int { kStarting = 0, kReady = 1, kFailed = 2 };
std::atomic<int> g_state{kStarting};
struct BootStep {
  const char* label;
  uint32_t ms;
};
BootStep g_steps[8];
int g_step_count = 0;
uint32_t g_done_ms = 0;

void step(const char* label) {
  Serial.printf("boot: %s\n", label);
  if (g_step_count < 8) g_steps[g_step_count++] = {label, millis()};
}

void radio_task(void*) {
  // The bus is ours until the radio is up and has announced (spi_bus.h).
  spi_bus::lock();
  step("Starting LoRa radio");
#ifdef WAYPOST_TEST_SLOW_RADIO_MS
  delay(WAYPOST_TEST_SLOW_RADIO_MS);  // test builds only: simulate a slow radio
#endif
  g_lora_interface = new LoRaInterface();
  g_lora_interface.mode(RNS::Type::Interface::MODE_GATEWAY);
  RNS::Transport::register_interface(g_lora_interface);
  if (!g_lora_interface.start()) {
    spi_bus::unlock();
    Serial.println("link: LoRa init failed");
    g_done_ms = millis();
    g_state.store(kFailed, std::memory_order_release);
    vTaskDelete(nullptr);
    return;
  }

  step("Starting Reticulum");
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
  RNS::Transport::register_announce_handler(RNS::HAnnounceHandler(new OutpostWatcher()));

  step("Loading identity");
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
  step("Announcing");
  g_destination.announce();

  Serial.printf("Scout Reticulum destination: %s\n", g_dest_hex.c_str());
  Serial.printf("device_class=pocket node_id=%s\n", g_node_id.c_str());
  g_done_ms = millis();
  spi_bus::unlock();
  g_state.store(kReady, std::memory_order_release);
  vTaskDelete(nullptr);
}

}  // namespace

bool mount_storage() {
  step("Mounting storage");
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

  return true;
}

void start_radio() {
  // Core 0, so the UI's loop() (core 1) keeps running. The display and the
  // radio share one SPI bus: the task holds spi_bus while it uses it, and
  // the UI skips screen refreshes until it's done.
  xTaskCreatePinnedToCore(radio_task, "radio_boot", 24576, nullptr, 1, nullptr, 0);
}

bool ready() { return g_state.load(std::memory_order_acquire) == kReady; }
bool failed() { return g_state.load(std::memory_order_acquire) == kFailed; }

std::string boot_timing() {
  if (g_state.load(std::memory_order_acquire) == kStarting || g_step_count == 0) return "";
  std::string detail, slowest = g_steps[0].label;
  uint32_t slowest_ms = 0;
  for (int i = 0; i < g_step_count; i++) {
    uint32_t end = i + 1 < g_step_count ? g_steps[i + 1].ms : g_done_ms;
    uint32_t ms = end - g_steps[i].ms;
    detail += std::string(" ") + g_steps[i].label + "=" + std::to_string(ms) + "ms";
    if (ms > slowest_ms) {
      slowest_ms = ms;
      slowest = g_steps[i].label;
    }
  }
  return std::to_string(g_done_ms / 1000) + " s" + (failed() ? " (radio FAILED)" : "") +
         "; slowest: " + slowest + " " + std::to_string(slowest_ms / 1000) + "." +
         std::to_string(slowest_ms / 100 % 10) + " s\n" + detail;
}

void loop() {
  if (!ready()) return;  // the radio task still owns Reticulum
  g_reticulum.loop();
  static uint32_t last_announce = millis();
  if (millis() - last_announce >= kReannounceMs) {
    if (g_destination) g_destination.announce();
    last_announce = millis();
  }
}

// Written by the radio task; only read once it has published ready().
const std::string& node_id() {
  static const std::string starting = std::string(WAYPOST_POCKET_ID) + " (radio starting)";
  return ready() ? g_node_id : starting;
}
const std::string& dest_hex() {
  static const std::string none;
  return ready() ? g_dest_hex : none;
}

bool station_known() {
  if (!ready() || station_quiet()) return false;
  RNS::Bytes hash;
  return station_hash(hash) && RNS::Transport::has_path(hash) &&
         static_cast<bool>(RNS::Identity::recall(hash));
}

void seek_station() {
  if (!ready()) return;
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
    case Result::NotReady: return failed() ? "the radio failed to start" : "the radio is still starting";
  }
  return "?";
}

namespace {
Result request_impl(const RNS::Bytes& to, const Builder& build, waylink::Reply& out, int attempts,
                    uint32_t timeout_ms) {
  RNS::Destination dest({RNS::Type::NONE});
  if (!(to.size() == 16 ? connect_to(to, dest) : connect(dest))) return Result::NoPath;

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
  RNS::Bytes station;
  if (to.size() != 16 || (station_hash(station) && to == station)) {
    g_station_quiet_until = (millis() + kQuietMs) | 1;
    Serial.println("link: Station isn't answering - treating it as out of reach for 2 min");
  }
  return Result::Timeout;
}
}  // namespace

Result request(const Builder& build, waylink::Reply& out, int attempts, uint32_t timeout_ms) {
  if (!ready()) return Result::NotReady;
  busy_tick();
  Result r = request_impl(RNS::Bytes(), build, out, attempts, timeout_ms);
  busy_done();
  return r;
}

Result request(const char* svc, const char* op, const std::vector<waylink::Field>& payload,
               waylink::Reply& out, int attempts, uint32_t timeout_ms, uint64_t ts) {
  return request(
      [&](const std::string& mid, const std::string& rid) {
        return waylink::encode_request(node_id().c_str(), kStationNodeId, mid, rid, svc, op,
                                       120, payload, ts);
      },
      out, attempts, timeout_ms);
}

RNS::Bytes encode(const char* svc, const char* op, const std::vector<waylink::Field>& payload,
                  uint64_t ts) {
  // Same lengths as real ids (new_id(): 16 hex characters).
  return waylink::encode_request(node_id().c_str(), kStationNodeId, "0123456789abcdef",
                                 "0123456789abcdef", svc, op, 120, payload, ts);
}

RNS::Bytes station_dest() {
  RNS::Bytes hash;
  station_hash(hash);
  return hash;
}

Result request_peer(const RNS::Bytes& dest, const char* dst_node, const char* svc, const char* op,
                    const waylink::Value& payload, waylink::Reply& out, int attempts,
                    uint32_t timeout_ms) {
  if (!ready()) return Result::NotReady;
  return request_impl(
      dest,
      [&](const std::string& mid, const std::string& rid) {
        return waylink::encode_envelope(node_id().c_str(), dst_node, mid, rid, svc, op, 1, 120, 0,
                                        payload);
      },
      out, attempts, timeout_ms);
}

bool send_to(const RNS::Bytes& dest, const RNS::Bytes& payload) {
  if (!ready()) return false;
  RNS::Destination d({RNS::Type::NONE});
  if (!connect_to(dest, d)) return false;
  RNS::Packet pkt(d, payload);
  pkt.send();
  return true;
}

std::vector<std::string> outposts_heard() { return g_outposts; }

bool has_path(const RNS::Bytes& dest) { return ready() && RNS::Transport::has_path(dest); }

bool send(const RNS::Bytes& payload) {
  if (!ready()) return false;
  RNS::Destination dest({RNS::Type::NONE});
  if (!connect(dest)) return false;
  RNS::Packet pkt(dest, payload);
  pkt.send();
  return true;
}

RNS::Bytes identity_public_key() { return g_identity ? g_identity.get_public_key() : RNS::Bytes(); }
RNS::Bytes identity_hash() { return g_identity ? g_identity.hash() : RNS::Bytes(); }
RNS::Bytes identity_sign(const RNS::Bytes& message) {
  return g_identity ? g_identity.sign(message) : RNS::Bytes();
}

uint64_t now_ms() {
  if (g_epoch_s == 0) return 0;
  return g_epoch_s * 1000ULL + static_cast<uint32_t>(millis() - g_epoch_at_ms);
}

bool pop_event(waylink::Reply& out) {
  if (g_events.empty()) return false;
  out = std::move(g_events.front());
  g_events.pop_front();
  return true;
}

bool pop_incoming(waylink::IncomingChatMessage& out) {
  if (g_incoming.empty()) return false;
  out = std::move(g_incoming.front());
  g_incoming.pop_front();
  return true;
}

}  // namespace station_link
