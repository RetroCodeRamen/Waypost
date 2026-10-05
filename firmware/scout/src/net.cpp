#include "net.h"

// microStore's headers need <string> before them (see pocket's main.cpp).
#include <string>
#include <vector>

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <microStore/Adapters/LittleFSFileSystem.h>
#include <microStore/FileSystem.h>
#include <microReticulum.h>
#include <waylink_cbor.h>

#ifndef WAYPOST_POCKET_ID
#define WAYPOST_POCKET_ID "pocket-1"
#endif
#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif

namespace net {
namespace {

const char* const kAppName = "waypost";
const char* const kAspect = "waylink";
const char* const kIdentityPath = "/waypost_identity";
const char* const kStationNodeId = "station";
constexpr uint32_t kReannounceMs = 10UL * 60UL * 1000UL;
constexpr uint32_t kPingTimeoutMs = 15000;
constexpr uint32_t kFloodGapMs = 300;
// has_path()/recall() read flash (~45 ms each): ask at most this often.
constexpr uint32_t kPathCheckMs = 2000;

QueueHandle_t g_commands = nullptr;
SemaphoreHandle_t g_status_lock = nullptr;
Status g_status;

RNS::Reticulum g_reticulum({RNS::Type::NONE});
RNS::Interface g_interface({RNS::Type::NONE});
radio::AsyncLoRa* g_lora = nullptr;
RNS::Identity g_identity({RNS::Type::NONE});
RNS::Destination g_destination({RNS::Type::NONE});
RNS::Destination g_station({RNS::Type::NONE});
RNS::Bytes g_station_hash;
std::string g_node_id = WAYPOST_POCKET_ID;

// The one PING in flight.
std::string g_ping_rid;
uint32_t g_ping_at = 0;
bool g_flood = false;
bool g_ping_wanted = false;
uint32_t g_next_flood = 0;

template <typename F>
void update(F f) {
  xSemaphoreTake(g_status_lock, portMAX_DELAY);
  f(g_status);
  xSemaphoreGive(g_status_lock);
}

void step(const char* label) {
  Serial.printf("net: %s\n", label);
  update([&](Status& s) { s.step = label; });
}

// Runs inside g_reticulum.loop(), on this task. Never sends from here.
void on_packet(const RNS::Bytes& data, const RNS::Packet&) {
  waylink::Reply reply;
  if (!waylink::parse_reply(data.data(), data.size(), reply)) return;
  if (!g_ping_rid.empty() && reply.rid == g_ping_rid) {
    uint32_t rtt = millis() - g_ping_at;
    g_ping_rid.clear();
    g_next_flood = millis() + kFloodGapMs;
    update([&](Status& s) {
      s.pings_ok++;
      s.last_rtt_ms = rtt;
    });
    Serial.printf("net: PING reply in %lu ms\n", static_cast<unsigned long>(rtt));
  }
}

bool mount_storage() {
  static microStore::FileSystem fs{microStore::Adapters::LittleFSFileSystem()};
  fs.init(false);
  RNS::Utilities::OS::register_filesystem(fs);
  // microReticulum's stores need absolute, existing directories.
  for (const char* dir : {"/rns", "/cache", "/path_store", "/known_store", "/hashlist_store"})
    fs.mkdir(dir);
  return true;
}

bool bring_up() {
  step("mounting storage");
  mount_storage();

  step("starting radio");
  g_lora = new radio::AsyncLoRa();
  g_interface = g_lora;
  g_interface.mode(RNS::Type::Interface::MODE_GATEWAY);
  RNS::Transport::register_interface(g_interface);
  if (!g_interface.start()) return false;

  step("starting Reticulum");
  g_reticulum = RNS::Reticulum();
  RNS::Reticulum::storagepath("/rns");
  g_reticulum.transport_enabled(true);
  g_reticulum.probe_destination_enabled(false);       // nothing probes a Scout
  RNS::Reticulum::neighbor_probing_enabled(false);  // Station never proves Waylink packets
  g_reticulum.start();

  step("loading identity");
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
  update([&](Status& s) { strlcpy(s.dest, hex.c_str(), sizeof(s.dest)); });

  step("announcing");
  g_destination.announce();
  g_station_hash.assignHex(WAYPOST_STATION_DEST_HASH);
  Serial.printf("net: ready, destination %s\n", hex.c_str());
  return true;
}

// Station's destination, once its path and identity are known. Checked on
// a timer, never per pass.
bool station_ready() {
  static uint32_t last = 0;
  static bool known = false;
  if (g_station) return true;
  if (g_station_hash.size() != 16) return false;
  if (last && millis() - last < kPathCheckMs) return known;
  last = millis();
  known = RNS::Transport::has_path(g_station_hash);
  if (!known) {
    static uint32_t asked = 0;
    if (!asked || millis() - asked > 30000) {
      RNS::Transport::request_path(g_station_hash);
      asked = millis();
    }
    return false;
  }
  RNS::Identity id = RNS::Identity::recall(g_station_hash);
  if (!id) return false;
  g_station = RNS::Destination(id, RNS::Type::Destination::OUT, RNS::Type::Destination::SINGLE,
                               kAppName, kAspect);
  update([](Status& s) { s.station_path = true; });
  return true;
}

void send_ping() {
  std::string mid = waylink::new_hex_id();
  g_ping_rid = waylink::new_hex_id();
  g_ping_at = millis();
  RNS::Bytes req = waylink::encode_request(g_node_id.c_str(), kStationNodeId, mid, g_ping_rid,
                                           "CORE", "PING", 120, {});
  RNS::Packet(g_station, req).send();  // queues on the radio; returns at once
  update([](Status& s) { s.pings_sent++; });
}

void run_jobs() {
  Command c;
  while (xQueueReceive(g_commands, &c, 0) == pdTRUE) {
    switch (c) {
      case Command::Ping: g_ping_wanted = true; break;
      case Command::ToggleFlood:
        g_flood = !g_flood;
        update([](Status& s) { s.flooding = g_flood; });
        break;
      case Command::Announce: g_destination.announce(); break;
    }
  }

  if (!g_ping_rid.empty() && millis() - g_ping_at > kPingTimeoutMs) {
    g_ping_rid.clear();
    g_next_flood = millis() + kFloodGapMs;
    update([](Status& s) { s.pings_lost++; });
    Serial.println("net: PING timed out");
  }
  bool due = g_ping_wanted || (g_flood && static_cast<int32_t>(millis() - g_next_flood) >= 0);
  if (due && g_ping_rid.empty() && station_ready()) {
    g_ping_wanted = false;
    send_ping();
  }
  if (!g_station) station_ready();

  static uint32_t last_announce = millis();
  if (millis() - last_announce >= kReannounceMs) {
    g_destination.announce();
    last_announce = millis();
  }
}

void task(void*) {
  radio::set_wake_task(xTaskGetCurrentTaskHandle());
  if (!bring_up()) {
    step("radio failed to start");
    update([](Status& s) { s.stage = Stage::Failed; });
    vTaskDelete(nullptr);
    return;
  }
  update([](Status& s) { s.stage = Stage::Ready; s.step = "ready"; });

  uint32_t window = millis(), worst = 0;
  for (;;) {
    // Sleep until the radio interrupts or 5 ms pass.
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(5));
    uint32_t t0 = millis();
    g_reticulum.loop();  // also runs the radio's state machine
    run_jobs();
    worst = std::max<uint32_t>(worst, millis() - t0);
    if (millis() - window >= 1000) {
      radio::Stats rs = g_lora->stats();
      uint32_t w = worst;
      update([&](Status& s) {
        s.radio = rs;
        s.loop_max_ms = w;
      });
      window = millis();
      worst = 0;
    }
  }
}

}  // namespace

void start() {
  g_commands = xQueueCreate(16, sizeof(Command));
  g_status_lock = xSemaphoreCreateMutex();
  // Core 0 (the UI task is on core 1). Big stack: Reticulum's crypto.
  xTaskCreatePinnedToCore(task, "net", 32768, nullptr, 2, nullptr, 0);
}

void send(Command c) { xQueueSend(g_commands, &c, 0); }

Status status() {
  Status copy;
  xSemaphoreTake(g_status_lock, portMAX_DELAY);
  copy = g_status;
  xSemaphoreGive(g_status_lock);
  return copy;
}

}  // namespace net
