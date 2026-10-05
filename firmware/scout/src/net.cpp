#include "net.h"

// microStore's headers need <string> before them (see pocket's main.cpp).
#include <string>
#include <algorithm>
#include <deque>
#include <map>
#include <vector>

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <microStore/Adapters/LittleFSFileSystem.h>
#include <microStore/FileSystem.h>
#include <microReticulum.h>

#ifndef WAYPOST_POCKET_ID
#define WAYPOST_POCKET_ID "pocket-1"
#endif
#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif

namespace net {

const char* const kStationNodeId = "station";

namespace {

const char* const kAppName = "waypost";
const char* const kAspect = "waylink";
const char* const kIdentityPath = "/waypost_identity";
constexpr uint32_t kReannounceMs = 10UL * 60UL * 1000UL;
constexpr uint32_t kPathWaitMs = 12000;   // a request waits this long for a path
constexpr uint32_t kPathPollMs = 500;     // has_path reads flash: not every pass
constexpr uint32_t kPathAskMs = 30000;    // request_path at most this often per destination
constexpr uint32_t kQuietMs = 2UL * 60UL * 1000UL;  // Station stopped answering
// One request on the air at a time: LoRa is half duplex, and a second
// request sent while Station's reply to the first is arriving loses the
// reply (seen with two: MSG_SYNC replies never arrived).
constexpr int kInFlight = 1;

// -- shared with other tasks (g_lock) ---------------------------------------------

SemaphoreHandle_t g_lock = nullptr;
struct Lock {
  Lock() { xSemaphoreTake(g_lock, portMAX_DELAY); }
  ~Lock() { xSemaphoreGive(g_lock); }
};

struct Done {
  Result r;
  waylink::Reply reply;
};

uint32_t g_next_id = 1;
std::deque<std::pair<uint32_t, Request>> g_new;  // requests not yet taken by the task
std::map<uint32_t, Done> g_done;
std::vector<uint32_t> g_forgotten;
int g_pending = 0;
std::deque<std::pair<RNS::Bytes, RNS::Bytes>> g_sends;
std::deque<Incoming> g_incoming;
Status g_status;
uint64_t g_epoch_s = 0;
uint32_t g_epoch_at_ms = 0;

struct PathEntry {
  bool known = false;
  uint32_t checked_at = 0;  // 0 = never
  uint32_t asked_at = 0;
  bool wanted = false;      // someone asked; refresh when stale
};
std::map<std::string, PathEntry> g_paths;  // dest hex

// -- the net task's own state -----------------------------------------------------

RNS::Reticulum g_reticulum({RNS::Type::NONE});
RNS::Interface g_interface({RNS::Type::NONE});
radio::AsyncLoRa* g_lora = nullptr;
RNS::Identity g_identity({RNS::Type::NONE});
RNS::Destination g_destination({RNS::Type::NONE});
RNS::Bytes g_station_hash;
std::string g_node_id;
std::map<std::string, RNS::Destination> g_dests;  // resolved OUT destinations
uint32_t g_station_quiet_until = 0;

struct Job {
  uint32_t id;
  Request req;
  RNS::Bytes hash;
  int attempt = 0;
  bool sent = false;
  uint32_t since = 0;  // waiting for a path since / attempt sent at
  uint32_t path_polled = 0;
  std::string rid;
  bool replied = false;
  waylink::Reply reply;
};
std::deque<Job> g_jobs;

bool station_quiet() {
  return g_station_quiet_until && static_cast<int32_t>(millis() - g_station_quiet_until) < 0;
}

void finish(Job& j, Result r, waylink::Reply reply = waylink::Reply()) {
  Lock l;
  g_pending--;
  auto f = std::find(g_forgotten.begin(), g_forgotten.end(), j.id);
  if (f != g_forgotten.end()) {
    g_forgotten.erase(f);
    return;
  }
  g_done[j.id] = Done{r, std::move(reply)};
}

// -- receiving --------------------------------------------------------------------

// Runs inside g_reticulum.loop(), on this task. Never sends from here.
void on_packet(const RNS::Bytes& data, const RNS::Packet&) {
  waylink::IncomingChatMessage msg;
  if (waylink::decode_msg_push(data.data(), data.size(), msg)) {
    Lock l;
    if (g_incoming.size() < 16) {
      Incoming in;
      in.kind = Incoming::Chat;
      in.chat = std::move(msg);
      g_incoming.push_back(std::move(in));
    }
    return;
  }
  waylink::Reply reply;
  if (!waylink::parse_reply(data.data(), data.size(), reply)) {
    Serial.println("net: undecodable packet dropped");
    return;
  }
  bool from_station = reply.envelope.text("src") == kStationNodeId;
  if (from_station) {
    g_station_quiet_until = 0;  // it's back
    // Wall clock from Station only: a peer's clock may be wrong.
    uint64_t ts = reply.envelope.uint("ts");
    if (ts > 1600000000ULL) {
      Lock l;
      g_epoch_s = ts;
      g_epoch_at_ms = millis();
    }
  }
  // A REQUEST that isn't a RESPONSE is someone telling us something
  // unprompted (Flags.REQUEST = 1, RESPONSE = 2).
  if ((reply.flags & 1) && !(reply.flags & 2)) {
    Lock l;
    if (g_incoming.size() < 16) {
      Incoming in;
      in.kind = Incoming::Event;
      in.event = std::move(reply);
      g_incoming.push_back(std::move(in));
    }
    return;
  }
  for (auto& j : g_jobs) {
    if (j.sent && !j.replied && j.rid == reply.rid) {
      j.replied = true;
      j.reply = std::move(reply);
      return;
    }
  }
  Serial.printf("net: stale reply rid=%s dropped\n", reply.rid.c_str());
}

class OutpostWatcher : public RNS::AnnounceHandler {
 public:
  OutpostWatcher() : RNS::AnnounceHandler("waypost.waylink") {}
  void received_announce(const RNS::Bytes& destination_hash, const RNS::Identity&,
                         const RNS::Bytes& app_data) override {
    std::string ad(reinterpret_cast<const char*>(app_data.data()), app_data.size());
    if (ad.compare(0, 14, "WPOST-OUTPOST:") != 0 && ad.compare(0, 12, "WPOST-CLAIM:") != 0) return;
    std::string hex = destination_hash.toHex();
    Lock l;
    auto& v = g_status.outposts;
    if (std::find(v.begin(), v.end(), hex) != v.end()) return;
    if (v.size() >= 8) v.erase(v.begin());
    v.push_back(hex);
    Serial.printf("net: Outpost heard %s\n", hex.c_str());
  }
};

// -- paths ------------------------------------------------------------------------

// A resolved destination for `hash`, if its path and identity are known.
// Asks for a path (throttled) when not. Reads flash: callers throttle.
bool resolve(const RNS::Bytes& hash, RNS::Destination& out) {
  std::string hex = hash.toHex();
  auto it = g_dests.find(hex);
  if (it != g_dests.end()) {
    out = it->second;
    return true;
  }
  if (!RNS::Transport::has_path(hash)) {
    Lock l;
    PathEntry& p = g_paths[hex];
    if (!p.asked_at || millis() - p.asked_at > kPathAskMs) {
      p.asked_at = millis() | 1;
      RNS::Transport::request_path(hash);
    }
    return false;
  }
  RNS::Identity id = RNS::Identity::recall(hash);
  if (!id) return false;
  out = RNS::Destination(id, RNS::Type::Destination::OUT, RNS::Type::Destination::SINGLE,
                         kAppName, kAspect);
  g_dests.emplace(hex, out);
  return true;
}

// One stale path-cache entry per call (each check reads flash).
void refresh_paths() {
  static uint32_t last = 0;
  if (millis() - last < 250) return;
  last = millis();
  std::string hex;
  {
    Lock l;
    for (auto& kv : g_paths) {
      PathEntry& p = kv.second;
      if (!p.wanted) continue;
      if (!p.checked_at || millis() - p.checked_at > 2000) {
        hex = kv.first;
        break;
      }
    }
  }
  if (hex.empty()) return;
  RNS::Bytes hash;
  hash.assignHex(hex.c_str());
  bool known = g_dests.count(hex) || RNS::Transport::has_path(hash);
  uint32_t now = millis();
  bool ask = false;
  {
    Lock l;
    PathEntry& p = g_paths[hex];
    p.known = known;
    p.checked_at = now | 1;
    if (!known && (!p.asked_at || now - p.asked_at > kPathAskMs)) {
      p.asked_at = now | 1;
      ask = true;
    }
  }
  if (ask) RNS::Transport::request_path(hash);
}

// -- requests ---------------------------------------------------------------------

void send_attempt(Job& j, const RNS::Destination& dest) {
  std::string mid = waylink::new_hex_id();
  j.rid = waylink::new_hex_id();
  j.attempt++;
  j.sent = true;
  j.replied = false;
  j.since = millis();
  const Request& r = j.req;
  const char* dst = r.dst_node.empty() ? kStationNodeId : r.dst_node.c_str();
  RNS::Bytes bytes = r.use_tree
                         ? waylink::encode_envelope(g_node_id.c_str(), dst, mid, j.rid, r.svc.c_str(),
                                                    r.op.c_str(), 1, 120, r.ts, r.tree)
                         : waylink::encode_request(g_node_id.c_str(), dst, mid, j.rid, r.svc.c_str(),
                                                   r.op.c_str(), 120, r.fields, r.ts);
  RNS::Packet(dest, bytes).send();  // queued on the radio; returns at once
}

// Moves one job along. True when it's finished (remove it).
bool step(Job& j) {
  if (j.replied) {
    Result r = j.reply.error.empty() ? Result::Ok : Result::Error;
    if (r == Result::Ok)
      Serial.printf("net: %s %s in %lu ms (attempt %d)\n", j.req.svc.c_str(), j.req.op.c_str(),
                    static_cast<unsigned long>(millis() - j.since), j.attempt);
    finish(j, r, std::move(j.reply));
    return true;
  }
  if (!j.sent) {
    if (j.hash.size() != 16) {
      finish(j, Result::NoPath);
      return true;
    }
    bool to_station = j.hash == g_station_hash;
    if (to_station && station_quiet()) {
      finish(j, Result::Timeout);
      return true;
    }
    if (millis() - j.path_polled < kPathPollMs && j.path_polled) return false;
    j.path_polled = millis();
    RNS::Destination dest({RNS::Type::NONE});
    if (resolve(j.hash, dest)) {
      send_attempt(j, dest);
      return false;
    }
    if (millis() - j.since > kPathWaitMs) {
      finish(j, Result::NoPath);
      return true;
    }
    return false;
  }
  if (millis() - j.since < j.req.timeout_ms) return false;
  Serial.printf("net: %s %s attempt %d/%d timed out\n", j.req.svc.c_str(), j.req.op.c_str(),
                j.attempt, j.req.attempts);
  auto d = g_dests.find(j.hash.toHex());
  if (j.attempt < j.req.attempts && d != g_dests.end()) {
    send_attempt(j, d->second);
    return false;
  }
  if (j.hash == g_station_hash) {
    g_station_quiet_until = (millis() + kQuietMs) | 1;
    Serial.println("net: Station isn't answering - out of reach for 2 min");
  }
  finish(j, Result::Timeout);
  return true;
}

void run_requests() {
  // Take new requests.
  {
    Lock l;
    while (!g_new.empty()) {
      Job j;
      j.id = g_new.front().first;
      j.req = std::move(g_new.front().second);
      g_new.pop_front();
      j.hash = j.req.dest.size() == 16 ? j.req.dest : g_station_hash;
      j.since = millis();
      g_jobs.push_back(std::move(j));
    }
    // Forgotten before they started: drop.
    for (auto it = g_jobs.begin(); it != g_jobs.end();) {
      auto f = std::find(g_forgotten.begin(), g_forgotten.end(), it->id);
      if (f != g_forgotten.end() && !it->sent) {
        g_forgotten.erase(f);
        g_pending--;
        it = g_jobs.erase(it);
      } else {
        ++it;
      }
    }
  }
  // Oldest first; at most kInFlight on the air.
  int in_flight = 0;
  for (auto it = g_jobs.begin(); it != g_jobs.end();) {
    bool active = it->sent || in_flight < kInFlight;
    if (!active) {
      it->since = millis();  // its path wait starts when it gets a turn
      ++it;
      continue;
    }
    if (step(*it)) {
      it = g_jobs.erase(it);
      continue;
    }
    if (it->sent) in_flight++;
    ++it;
  }
}

void run_sends() {
  std::pair<RNS::Bytes, RNS::Bytes> s;
  {
    Lock l;
    if (g_sends.empty()) return;
    s = std::move(g_sends.front());
    g_sends.pop_front();
  }
  RNS::Bytes hash = s.first.size() == 16 ? s.first : g_station_hash;
  RNS::Destination dest({RNS::Type::NONE});
  if (!resolve(hash, dest)) {
    Serial.println("net: no path, packet dropped");
    return;
  }
  RNS::Packet(dest, s.second).send();
}

// -- bring-up ---------------------------------------------------------------------

}  // namespace

void mount_storage() {
  static microStore::FileSystem fs{microStore::Adapters::LittleFSFileSystem()};
  fs.init(false);
  RNS::Utilities::OS::register_filesystem(fs);
  // microReticulum's stores need absolute, existing directories.
  for (const char* dir : {"/rns", "/cache", "/path_store", "/known_store", "/hashlist_store"})
    fs.mkdir(dir);
}

namespace {

std::string g_boot;
void step_log(const char* label) {
  static uint32_t t0 = millis(), last = t0;
  if (!g_boot.empty()) g_boot += " ";
  uint32_t now = millis();
  g_boot += label + std::string("=") + std::to_string(now - last) + "ms";
  last = now;
  Serial.printf("net: %s\n", label);
}

bool bring_up() {
  step_log("start");
  g_lora = new radio::AsyncLoRa();
  g_interface = g_lora;
  g_interface.mode(RNS::Type::Interface::MODE_GATEWAY);
  RNS::Transport::register_interface(g_interface);
  if (!g_interface.start()) return false;
  step_log("radio");

  g_reticulum = RNS::Reticulum();
  RNS::Reticulum::storagepath("/rns");
  g_reticulum.transport_enabled(true);
  g_reticulum.probe_destination_enabled(false);     // nothing probes a Scout
  RNS::Reticulum::neighbor_probing_enabled(false);  // Station never proves Waylink packets
  g_reticulum.start();
  RNS::Transport::register_announce_handler(RNS::HAnnounceHandler(new OutpostWatcher()));
  step_log("reticulum");

  g_identity = RNS::Identity::from_file(kIdentityPath);
  if (!g_identity) {
    Serial.println("net: no saved identity, making one");
    g_identity = RNS::Identity();
    g_identity.to_file(kIdentityPath);
  }
  g_destination = RNS::Destination(g_identity, RNS::Type::Destination::IN,
                                   RNS::Type::Destination::SINGLE, kAppName, kAspect);
  g_destination.set_packet_callback(on_packet);
  std::string hex = g_destination.hash().toHex();
  g_node_id = std::string(WAYPOST_POCKET_ID) + "-" + hex.substr(0, 4);
  step_log("identity");

  g_destination.announce();
  step_log("announce");
  Serial.printf("net: ready, destination %s, node %s\n", hex.c_str(), g_node_id.c_str());
  Lock l;
  g_status.node_id = g_node_id;
  g_status.dest_hex = hex;
  g_status.boot = std::to_string(millis() / 1000) + " s: " + g_boot;
  return true;
}

void task(void*) {
  radio::set_wake_task(xTaskGetCurrentTaskHandle());
  if (!bring_up()) {
    Serial.println("net: radio failed to start");
    Lock l;
    g_status.failed = true;
    g_status.boot = "radio FAILED: " + g_boot;
    // Fail every request from now on.
    for (;;) {
      while (!g_new.empty()) {
        g_done[g_new.front().first] = Done{Result::NotReady, waylink::Reply()};
        g_new.pop_front();
        g_pending--;
      }
      xSemaphoreGive(g_lock);
      vTaskDelay(pdMS_TO_TICKS(100));
      xSemaphoreTake(g_lock, portMAX_DELAY);
    }
  }
  {
    Lock l;
    g_status.ready = true;
    g_paths[g_station_hash.toHex()].wanted = true;
  }

  uint32_t last_announce = millis(), last_status = 0;
  for (;;) {
    // Sleep until the radio interrupts or 5 ms pass.
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(5));
    g_reticulum.loop();  // also runs the radio's state machine
    run_requests();
    run_sends();
    refresh_paths();
    if (millis() - last_announce >= kReannounceMs) {
      g_destination.announce();
      last_announce = millis();
    }
    if (millis() - last_status >= 250) {
      last_status = millis();
      radio::Stats rs = g_lora->stats();
      bool quiet = station_quiet();
      Lock l;
      g_status.radio = rs;
      const PathEntry& p = g_paths[g_station_hash.toHex()];
      g_status.station_known = p.known && !quiet;
    }
  }
}

}  // namespace

const char* describe(Result r) {
  switch (r) {
    case Result::Ok: return "ok";
    case Result::NoPath: return "no path to Station";
    case Result::Timeout: return "no reply from Station";
    case Result::Error: return "Station returned an error";
    case Result::NotReady: return "the radio isn't working";
  }
  return "?";
}

uint32_t request(Request r) {
  Lock l;
  uint32_t id = g_next_id++;
  if (!g_next_id) g_next_id = 1;
  g_pending++;
  g_new.push_back({id, std::move(r)});
  return id;
}

uint32_t request(const char* svc, const char* op, std::vector<waylink::Field> fields, int attempts,
                 uint32_t timeout_ms, uint64_t ts) {
  Request r;
  r.svc = svc;
  r.op = op;
  r.fields = std::move(fields);
  r.attempts = attempts;
  r.timeout_ms = timeout_ms;
  r.ts = ts;
  return request(std::move(r));
}

bool result(uint32_t id, Result& r, waylink::Reply& out) {
  Lock l;
  auto it = g_done.find(id);
  if (it == g_done.end()) return false;
  r = it->second.r;
  out = std::move(it->second.reply);
  g_done.erase(it);
  return true;
}

void forget(uint32_t id) {
  if (!id) return;
  Lock l;
  if (g_done.erase(id)) return;
  g_forgotten.push_back(id);
}

int pending() {
  Lock l;
  return g_pending;
}

void send(const RNS::Bytes& dest, const RNS::Bytes& payload) {
  Lock l;
  if (g_sends.size() < 16) g_sends.push_back({dest, payload});
}

bool incoming(Incoming& out) {
  Lock l;
  if (g_incoming.empty()) return false;
  out = std::move(g_incoming.front());
  g_incoming.pop_front();
  return true;
}

bool has_path(const RNS::Bytes& dest) {
  Lock l;
  PathEntry& p = g_paths[dest.toHex()];
  p.wanted = true;
  return p.known;
}

Status status() {
  Lock l;
  return g_status;
}

bool ready() {
  Lock l;
  return g_status.ready;
}

bool station_known() {
  Lock l;
  return g_status.station_known;
}

uint64_t now_ms() {
  Lock l;
  if (g_epoch_s == 0) return 0;
  return g_epoch_s * 1000ULL + static_cast<uint32_t>(millis() - g_epoch_at_ms);
}

RNS::Bytes station_dest() { return g_station_hash; }

size_t encoded_size(const char* svc, const char* op, const std::vector<waylink::Field>& fields,
                    uint64_t ts) {
  std::string node;
  {
    Lock l;
    node = g_status.node_id.empty() ? std::string(WAYPOST_POCKET_ID) + "-0000" : g_status.node_id;
  }
  // Same lengths as real ids (new_hex_id(): 16 hex characters).
  return waylink::encode_request(node.c_str(), kStationNodeId, "0123456789abcdef",
                                 "0123456789abcdef", svc, op, 120, fields, ts)
      .size();
}

void start() {
  g_lock = xSemaphoreCreateMutex();
  g_station_hash.assignHex(WAYPOST_STATION_DEST_HASH);
  // Core 0 (the UI task is on core 1). Big stack: Reticulum's crypto.
  xTaskCreatePinnedToCore(task, "net", 32768, nullptr, 2, nullptr, 0);
}

}  // namespace net
