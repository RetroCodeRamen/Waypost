/*
 * Waypost Scout — LilyGO T-Deck (M7).
 *
 * Product: Waypost Scout. Internal device class: Pocket — see docs/naming.md.
 *
 * Slice 1: microReticulum over SX1262 LoRa + Waylink CORE/PING round trip to
 * Station (optional DISPATCH/MSG_SEND when WAYPOST_DISPATCH_PEER is set).
 */

#include <string>
#include <vector>

#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>

#include <microStore/FileSystem.h>
#include <microStore/Adapters/LittleFSFileSystem.h>
#include <LoRaInterface.h>
#include <microReticulum.h>

#include "keyboard.h"
#include "utilities.h"
#include "waylink_cbor.h"
#include "waypost_mark.h"

#ifndef WAYPOST_POCKET_ID
#define WAYPOST_POCKET_ID "pocket-1"
#endif
#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif
#ifndef WAYPOST_DISPATCH_USER
#define WAYPOST_DISPATCH_USER "aj"
#endif
#ifndef WAYPOST_DISPATCH_PEER
#define WAYPOST_DISPATCH_PEER ""
#endif

static const char* STATION_NODE_ID = "station";
static const char* WAYPOST_APP_NAME = "waypost";
static const char* WAYPOST_ASPECT = "waylink";
static const char* IDENTITY_PATH = "/waypost_identity";

static const uint32_t BOOT_RADIO_DELAY_MS = 45UL * 1000UL;
static const uint32_t REANNOUNCE_INTERVAL_MS = 10UL * 60UL * 1000UL;

static TFT_eSPI g_tft;
static std::string g_pocket_id = WAYPOST_POCKET_ID;
static String g_status = "Starting radio...";
static String g_dest_hex;
static bool g_ping_ok = false;
static bool g_radio_test_done = false;

static RNS::Reticulum g_reticulum({RNS::Type::NONE});
static RNS::Interface g_lora_interface({RNS::Type::NONE});
static RNS::Identity g_identity({RNS::Type::NONE});
static RNS::Destination g_destination({RNS::Type::NONE});

static volatile bool g_reply_pending = false;
static RNS::Bytes g_reply_bytes;

// -- Chat (M7 slice 2): one default peer (WAYPOST_DISPATCH_PEER),
// Station-relayed via existing MSG_SEND/MSG_PUSH -- see
// docs/hardware/scout.md and this build's own plan notes for why
// Station-relay, not true P2P, is this slice's scope.
static constexpr size_t MAX_CHAT_LINES = 10;
static constexpr size_t MAX_INPUT_LEN = 200;
static bool g_chat_active = false;
static std::vector<std::string> g_chat_lines;
static std::string g_input_buffer;

struct PendingIncoming {
  std::string sender;
  std::string body;
  std::string message_id;
  std::string rid;
};
// Filled from on_destination_packet (runs synchronously inside
// g_reticulum.loop(), same thread as loop() itself -- no locking needed),
// drained in loop() so sending the ack never happens reentrantly from
// inside microReticulum's own packet callback.
static std::vector<PendingIncoming> g_incoming_queue;

static void board_power_on() {
  pinMode(BOARD_POWERON, OUTPUT);
  digitalWrite(BOARD_POWERON, HIGH);
}

static void backlight_on() {
  pinMode(BOARD_TFT_BACKLIGHT, OUTPUT);
  digitalWrite(BOARD_TFT_BACKLIGHT, HIGH);
}

static void draw_boot_ui() {
  g_tft.fillScreen(TFT_BLACK);
  g_tft.drawXBitmap((TFT_WIDTH - WAYPOST_MARK_WIDTH) / 2, 8, WAYPOST_MARK_BITS,
                    WAYPOST_MARK_WIDTH, WAYPOST_MARK_HEIGHT, TFT_WHITE);
  g_tft.setTextColor(TFT_WHITE, TFT_BLACK);
  g_tft.setTextDatum(MC_DATUM);
  g_tft.drawString("WAYPOST SCOUT", TFT_WIDTH / 2, 118, 4);
  g_tft.setTextDatum(TL_DATUM);
  g_tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  g_tft.drawString(g_pocket_id.c_str(), 8, 148, 2);
  if (g_dest_hex.length() > 0) {
    g_tft.drawString(("dest " + g_dest_hex.substring(0, 16) + "...").c_str(), 8, 166, 2);
  }
  g_tft.setTextColor(g_ping_ok ? TFT_GREEN : TFT_ORANGE, TFT_BLACK);
  g_tft.drawString(g_ping_ok ? "PING ok" : "PING --", 8, 188, 2);
  g_tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  g_tft.drawString(g_status, 8, TFT_HEIGHT - 36, 2);
}

static void draw_chat_ui() {
  g_tft.fillScreen(TFT_BLACK);
  g_tft.setTextDatum(TL_DATUM);

  g_tft.setTextColor(TFT_WHITE, TFT_BLACK);
  g_tft.drawString(("Scout <-> " + std::string(WAYPOST_DISPATCH_PEER)).c_str(), 4, 2, 2);
  g_tft.drawFastHLine(0, 20, TFT_WIDTH, TFT_DARKGREY);

  int y = 26;
  for (const auto& line : g_chat_lines) {
    g_tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    g_tft.drawString(line.c_str(), 4, y, 2);
    y += 18;
  }

  g_tft.drawFastHLine(0, TFT_HEIGHT - 36, TFT_WIDTH, TFT_DARKGREY);
  g_tft.setTextColor(TFT_GREEN, TFT_BLACK);
  g_tft.drawString(("> " + g_input_buffer + "_").c_str(), 4, TFT_HEIGHT - 30, 2);
  g_tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  g_tft.drawString(g_status, 4, TFT_HEIGHT - 14, 1);
}

static void draw_ui() {
  if (g_chat_active) {
    draw_chat_ui();
  } else {
    draw_boot_ui();
  }
}

static void set_status(const String& s) {
  g_status = s;
  draw_ui();
}

static void push_chat_line(const std::string& line) {
  g_chat_lines.push_back(line);
  if (g_chat_lines.size() > MAX_CHAT_LINES) {
    g_chat_lines.erase(g_chat_lines.begin());
  }
}

static void enter_chat_mode() {
  g_chat_active = true;
  g_input_buffer.clear();
  push_chat_line(g_ping_ok
                     ? "-- connected, type + Enter to send --"
                     : "-- no PING reply yet; messages retry their own path --");
  draw_ui();
}

static void on_destination_packet(const RNS::Bytes& data, const RNS::Packet& /*packet*/) {
  // A live, unsolicited DISPATCH/MSG_PUSH (someone messaged Scout's bound
  // user) is handled separately from a reply Scout is actively waiting
  // on -- decode_msg_push() only matches that specific shape (REQUEST
  // flag, svc/op match), so anything else -- including every reply this
  // firmware already awaits -- falls through to the existing behavior
  // unchanged. Queued, not handled here: see g_incoming_queue's comment
  // for why (no reentrant sends from inside this callback).
  waylink::IncomingChatMessage msg;
  if (waylink::decode_msg_push(data.data(), data.size(), msg)) {
    g_incoming_queue.push_back({msg.sender, msg.body, msg.message_id, msg.rid});
    return;
  }
  g_reply_bytes = data;
  g_reply_pending = true;
}

static void reticulum_setup() {
  static microStore::FileSystem filesystem{microStore::Adapters::LittleFSFileSystem()};
  filesystem.init(false);
  RNS::Utilities::OS::register_filesystem(filesystem);
  // microReticulum persistence stores — absolute paths, must exist before start()
  filesystem.mkdir("/rns");
  filesystem.mkdir("/cache");
  filesystem.mkdir("/path_store");
  filesystem.mkdir("/known_store");
  filesystem.mkdir("/hashlist_store");
  {
    RNS::Bytes canary_out("hello");
    size_t wrote = RNS::Utilities::OS::write_file("/canary.txt", canary_out);
    RNS::Bytes canary_in;
    size_t read = RNS::Utilities::OS::read_file("/canary.txt", canary_in);
    Serial.printf("canary: wrote=%u read=%u match=%d\n", (unsigned)wrote,
                  (unsigned)read, canary_in == canary_out);
  }

  g_lora_interface = new LoRaInterface();
  g_lora_interface.mode(RNS::Type::Interface::MODE_GATEWAY);
  RNS::Transport::register_interface(g_lora_interface);
  if (!g_lora_interface.start()) {
    set_status("LoRa init failed.");
    return;
  }

  g_reticulum = RNS::Reticulum();
  RNS::Reticulum::storagepath("/rns");
  // Match Outpost bring-up: transport mode helps path/announce handling on
  // microReticulum until Pocket courier relay policy is tuned separately.
  g_reticulum.transport_enabled(true);
  g_reticulum.probe_destination_enabled(true);
  g_reticulum.start();

  g_identity = RNS::Identity::from_file(IDENTITY_PATH);
  if (!g_identity) {
    Serial.println("No saved identity — generating a new one");
    g_identity = RNS::Identity();
    g_identity.to_file(IDENTITY_PATH);
  } else {
    Serial.println("Loaded saved identity from flash");
  }

  g_destination = RNS::Destination(
      g_identity,
      RNS::Type::Destination::IN,
      RNS::Type::Destination::SINGLE,
      WAYPOST_APP_NAME,
      WAYPOST_ASPECT);
  g_destination.set_packet_callback(on_destination_packet);

  g_pocket_id = std::string(WAYPOST_POCKET_ID) + "-" +
                g_destination.hash().toHex().substr(0, 4);
  g_dest_hex = g_destination.hash().toHex().c_str();
  g_destination.announce();

  Serial.print("Scout Reticulum destination: ");
  Serial.println(g_dest_hex);
  Serial.print("device_class=pocket node_id=");
  Serial.println(g_pocket_id.c_str());
  set_status("Radio up — waiting for path...");
}

static bool resolve_station(RNS::Bytes& station_hash) {
  static const char* hex = WAYPOST_STATION_DEST_HASH;
  if (strlen(hex) != 32) {
    set_status("Set WAYPOST_STATION_DEST_HASH in platformio.ini");
    return false;
  }
  station_hash.assignHex(hex);
  return station_hash.size() == 16;
}

static bool wait_for_path(const RNS::Bytes& station_hash, uint32_t timeout_ms) {
  if (RNS::Transport::has_path(station_hash)) {
    return true;
  }
  RNS::Transport::request_path(station_hash);
  uint32_t start = millis();
  while (millis() - start < timeout_ms) {
    g_reticulum.loop();
    if (RNS::Transport::has_path(station_hash)) {
      return true;
    }
    delay(50);
  }
  return false;
}

static bool connect_to_station(RNS::Destination& out_dest) {
  RNS::Bytes station_hash;
  if (!resolve_station(station_hash)) {
    return false;
  }
  if (!wait_for_path(station_hash, 12000)) {
    set_status("No path to Station yet.");
    Serial.println("connect: no path to Station.");
    return false;
  }
  RNS::Identity station_identity = RNS::Identity::recall(station_hash);
  if (!station_identity) {
    set_status("Station identity unknown — wait for announce.");
    Serial.println("connect: Identity::recall failed for Station.");
    return false;
  }
  Serial.println("connect: path + Station identity OK.");
  out_dest = RNS::Destination(
      station_identity,
      RNS::Type::Destination::OUT,
      RNS::Type::Destination::SINGLE,
      WAYPOST_APP_NAME,
      WAYPOST_ASPECT);
  return true;
}

static bool send_and_await_reply(
    const RNS::Destination& dest,
    const RNS::Bytes& payload,
    const std::string& expected_rid,
    waylink::SyncReplyResult& result) {
  g_reply_pending = false;
  RNS::Packet pkt(dest, payload);
  pkt.send();

  uint32_t start = millis();
  while (millis() - start < 15000) {
    g_reticulum.loop();
    if (g_reply_pending) break;
    delay(20);
  }
  if (!g_reply_pending) {
    Serial.println("send: reply timeout.");
    return false;
  }
  g_reply_pending = false;

  if (!waylink::decode_sync_reply(g_reply_bytes.data(), g_reply_bytes.size(), result) ||
      !result.parsed) {
    return false;
  }
  if (result.rid != expected_rid) {
    return false;
  }
  if (result.error || !result.ok) {
    return false;
  }
  return true;
}

static void run_radio_test() {
  RNS::Destination station_destination({RNS::Type::NONE});
  if (connect_to_station(station_destination)) {
    set_status("Path found — sending PING...");
    std::string mid = waylink::new_hex_id();
    std::string rid = waylink::new_hex_id();
    RNS::Bytes ping = waylink::encode_ping_request(
        g_pocket_id.c_str(), STATION_NODE_ID, mid, rid, 120);
    waylink::SyncReplyResult ping_result;
    if (send_and_await_reply(station_destination, ping, rid, ping_result)) {
      g_ping_ok = true;
      Serial.println("CORE/PING round trip OK.");
    } else {
      Serial.println("CORE/PING failed.");
    }
  } else {
    Serial.println("run_radio_test: no path to Station yet.");
  }
  // Enter chat regardless of the PING outcome -- it was only ever a
  // connectivity proof for the boot screen. A single lost packet is
  // ordinary LoRa behavior (confirmed repeatedly on this project's real
  // hardware) and shouldn't strand the user on the boot screen forever;
  // chat resolves its own path per message via connect_to_station() and
  // reports failure per-attempt, so there's nothing worth gating on here.
  enter_chat_mode();
}

// Outgoing: reuses encode_msg_send_request/send_and_await_reply exactly
// as run_radio_test() already did for its one hardcoded test message —
// now driven by the typed input line instead.
static void send_chat_message() {
  if (g_input_buffer.empty()) return;
  if (strlen(WAYPOST_DISPATCH_PEER) == 0) {
    push_chat_line("(no WAYPOST_DISPATCH_PEER configured)");
    draw_ui();
    return;
  }

  RNS::Destination station_destination({RNS::Type::NONE});
  if (!connect_to_station(station_destination)) {
    push_chat_line("(no path to Station)");
    draw_ui();
    return;
  }

  std::string body = g_input_buffer;
  g_input_buffer.clear();

  std::string mid = waylink::new_hex_id();
  std::string rid = waylink::new_hex_id();
  RNS::Bytes msg = waylink::encode_msg_send_request(
      g_pocket_id.c_str(),
      STATION_NODE_ID,
      mid,
      rid,
      120,
      WAYPOST_DISPATCH_USER,
      WAYPOST_DISPATCH_PEER,
      body.c_str());
  waylink::SyncReplyResult result;
  if (send_and_await_reply(station_destination, msg, rid, result)) {
    push_chat_line("me: " + body);
  } else {
    push_chat_line("me: " + body + "  (failed)");
  }
  draw_ui();
}

// Incoming: best-effort ack, same connect_to_station() helper the rest of
// this firmware already uses — returns near-instantly here since we just
// received a packet from Station, so its path/identity are already known.
// If this fails, Station simply hasn't marked the message delivered yet
// and will carry it as still-pending — nothing is lost.
static void send_ack_for(const PendingIncoming& incoming) {
  RNS::Destination station_destination({RNS::Type::NONE});
  if (!connect_to_station(station_destination)) return;
  RNS::Bytes ack = waylink::encode_msg_ack(
      g_pocket_id.c_str(), STATION_NODE_ID, incoming.rid, incoming.message_id);
  RNS::Packet pkt(station_destination, ack);
  pkt.send();
}

// Drains g_incoming_queue outside the packet callback (see its own
// comment) -- display first, ack after, same order a human reading the
// screen would expect.
static void drain_incoming() {
  if (g_incoming_queue.empty()) return;
  std::vector<PendingIncoming> batch;
  batch.swap(g_incoming_queue);
  for (const auto& incoming : batch) {
    push_chat_line(incoming.sender + ": " + incoming.body);
    send_ack_for(incoming);
  }
  draw_ui();
}

void setup() {
  Serial.begin(115200);
  uint32_t serial_start = millis();
  while (!Serial && millis() - serial_start < 3000) {
    delay(10);
  }

  board_power_on();
  delay(50);
  backlight_on();

  g_tft.init();
  g_tft.setRotation(1);
  draw_ui();

  keyboard::init();

  Serial.println();
  Serial.println("Waypost Scout — Reticulum slice");
  reticulum_setup();
}

static void poll_keyboard() {
  uint8_t key = keyboard::poll();
  if (key == 0) return;

  if (key == '\r' || key == '\n') {
    send_chat_message();
  } else if (key == 0x08 || key == 0x7F) {  // Backspace / Delete
    if (!g_input_buffer.empty()) {
      g_input_buffer.pop_back();
      draw_ui();
    }
  } else if (key >= 0x20 && key < 0x7F && g_input_buffer.size() < MAX_INPUT_LEN) {
    g_input_buffer.push_back(static_cast<char>(key));
    draw_ui();
  }
}

void loop() {
  g_reticulum.loop();

  static uint32_t last_announce = 0;
  if (millis() - last_announce >= REANNOUNCE_INTERVAL_MS) {
    if (g_destination) {
      g_destination.announce();
    }
    last_announce = millis();
  }

  static uint32_t boot_ms = millis();
  if (!g_radio_test_done && millis() - boot_ms >= BOOT_RADIO_DELAY_MS) {
    g_radio_test_done = true;
    run_radio_test();
  }

  drain_incoming();

  if (g_chat_active) {
    poll_keyboard();
  }

  delay(10);
}
