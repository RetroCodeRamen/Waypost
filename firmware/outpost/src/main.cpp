/*
 * Waypost Outpost — standalone Heltec V3: Wi-Fi AP + real Reticulum + Corkboard
 *
 * No host computer. This board runs the actual Reticulum protocol itself
 * via microReticulum (attermann/microReticulum, Apache-2.0) over its own
 * SX1262 LoRa radio, and serves a local Wi-Fi AP with a Corkboard
 * messageboard for visitors — see docs/architecture.md and this directory's
 * README for why (the earlier plaintext-LoRa draft was wrong: real
 * Reticulum on an ESP32 with no host is achievable via a reviewed library,
 * not hand-rolled crypto).
 *
 * Scope for this slice (see /home/aj/.claude/plans/wobbly-stargazing-adleman.md
 * at the time this was written, and firmware/outpost/README.md going
 * forward): in-RAM notes only, no flash persistence of the board itself
 * (the Reticulum identity IS persisted, in LittleFS, so this Outpost's
 * destination hash stays stable across reboots); Station's destination
 * hash is a manual build-time config, not auto-discovered.
 */

// <string>/<vector> must come first: microStore's File.h/FileSystem.h use
// std::string/std::to_string without including <string> themselves, so
// whichever translation unit includes them first has to supply it.
#include <string>
#include <vector>

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <U8g2lib.h>

#include <microStore/FileSystem.h>
#include <microStore/Adapters/LittleFSFileSystem.h>
#include <LoRaInterface.h>
#include <microReticulum.h>

#include "waylink_cbor.h"
#include "waypost_mark.h"

#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif
#ifndef WAYPOST_OUTPOST_ID
#define WAYPOST_OUTPOST_ID "outpost-1"
#endif
#ifndef WAYPOST_AP_SSID
#define WAYPOST_AP_SSID "WAYPOST-OUTPOST"
#endif

static const char* STATION_NODE_ID = "station";        // shared/... peer.py STATION_DEST
static const char* WAYPOST_APP_NAME = "waypost";        // must match server/transports/reticulum.py
static const char* WAYPOST_ASPECT = "waylink";           // APP_NAME / ASPECT exactly
static const char* IDENTITY_PATH = "/waypost_identity";
static const int PIN_VEXT = 36;  // shared power rail for OLED + LoRa TCXO on Heltec V3

static const size_t MAX_BODY = 500;       // server/services/corkboard/constants.py MAX_BODY
static const size_t MAX_SIGNATURE = 80;   // ...MAX_SIGNATURE
static const size_t MAX_NOTES = 40;       // in-RAM ring buffer cap, this slice only

struct Note {
  std::string id;
  std::string body;
  std::string signature;
  bool has_signature = false;
  bool synced = false;
};

static std::vector<Note> g_notes;
static String g_status = "Not synced with Station yet.";

static RNS::Reticulum g_reticulum({RNS::Type::NONE});
static RNS::Interface g_lora_interface({RNS::Type::NONE});
static RNS::Identity g_identity({RNS::Type::NONE});
static RNS::Destination g_destination({RNS::Type::NONE});

static WebServer g_server(80);

// OLED role splash — RST_OLED/SDA_OLED/SCL_OLED come from the board's own
// pins_arduino.h (verified against real hardware 2026-09-23: 21/17/18),
// not guessed. Same icon as firmware/heltec's Station splash; label text
// is what actually distinguishes the two boards at a glance.
static U8G2_SSD1306_128X64_NONAME_F_HW_I2C g_oled(U8G2_R0, /*reset=*/RST_OLED);

static void oled_init() {
  pinMode(RST_OLED, OUTPUT);
  digitalWrite(RST_OLED, LOW);
  delay(20);
  digitalWrite(RST_OLED, HIGH);
  delay(20);
  Wire.begin(SDA_OLED, SCL_OLED);
  g_oled.begin();
}

static void oled_center_text(const char* text, int y) {
  int w = g_oled.getStrWidth(text);
  int x = (128 - w) / 2;
  if (x < 0) x = 0;
  g_oled.drawStr(x, y, text);
}

static void oled_splash() {
  g_oled.clearBuffer();
  g_oled.drawXBMP((128 - WAYPOST_MARK_WIDTH) / 2, 0, WAYPOST_MARK_WIDTH,
                   WAYPOST_MARK_HEIGHT, WAYPOST_MARK_BITS);
  g_oled.setFont(u8g2_font_helvB12_tr);
  oled_center_text("OUTPOST", 62);
  g_oled.sendBuffer();
}

// Set by the packet callback, read back by refresh_board() after it pumps
// reticulum.loop() waiting for a reply. Single in-flight request at a time
// only (this firmware never has two /refresh calls overlapping — WebServer
// handles one request at a time).
static volatile bool g_reply_pending = false;
static RNS::Bytes g_reply_bytes;

static void on_destination_packet(const RNS::Bytes& data, const RNS::Packet& /*packet*/) {
  g_reply_bytes = data;
  g_reply_pending = true;
}

static void evict_if_full() {
  if (g_notes.size() >= MAX_NOTES) {
    g_notes.erase(g_notes.begin());
  }
}

static bool has_note(const std::string& id) {
  for (const auto& n : g_notes) {
    if (n.id == id) return true;
  }
  return false;
}

static String html_escape(const std::string& s) {
  String out;
  out.reserve(s.size());
  for (char c : s) {
    switch (c) {
      case '&': out += "&amp;"; break;
      case '<': out += "&lt;"; break;
      case '>': out += "&gt;"; break;
      case '"': out += "&quot;"; break;
      default: out += c; break;
    }
  }
  return out;
}

// -- Reticulum setup --

static void reticulum_setup() {
  static microStore::FileSystem filesystem{microStore::Adapters::LittleFSFileSystem()};
  // reformatOnFail=true would run LittleFSFileSystem's own self-test, which
  // writes to the RELATIVE path "./__init_test__" — ESP32's VFS rejects
  // any relative path outright, so that self-test always "fails" and would
  // reformat (wiping this Outpost's identity) on *every single boot*. This
  // was confirmed empirically during hardware bring-up (2026-09-23): the
  // destination hash changed on every reset until this was set to false.
  // LittleFS.begin(true, ...) inside init() still auto-formats on a
  // genuinely fresh/corrupt filesystem either way — that part is untouched.
  filesystem.init(false);
  RNS::Utilities::OS::register_filesystem(filesystem);

  g_lora_interface = new LoRaInterface();
  g_lora_interface.mode(RNS::Type::Interface::MODE_GATEWAY);
  RNS::Transport::register_interface(g_lora_interface);
  g_lora_interface.start();

  g_reticulum = RNS::Reticulum();
  // Reticulum()'s constructor resets storagepath() to "." — must be set
  // after construction, before start(). This only PARTIALLY fixes the
  // relative-path problem: Reticulum's own time_offset/transport_identity
  // files (opened lazily inside start()) do pick this up, confirmed via
  // the boot log during hardware bring-up (2026-09-23). Transport's
  // path/known/hashlist stores and its cache file do NOT — those are
  // static objects constructed before setup() ever runs, so they capture
  // "." regardless of anything application code does. Fixing that would
  // mean patching the vendored library, not something to do from here;
  // documented as a known limitation in firmware/outpost/README.md.
  // Net effect: this Outpost's own app identity below (read/written
  // directly via an absolute IDENTITY_PATH, not through these stores) is
  // unaffected and persists correctly; Reticulum's own path/announce
  // cache just starts cold each boot instead of warm.
  RNS::Reticulum::storagepath("/rns");
  filesystem.mkdir("/rns");
  // Outposts are relay infrastructure — Transport mode is what makes this
  // board actually forward path requests/announces for others "for free"
  // via microReticulum's own routing, rather than anything this firmware
  // writes itself (see docs/architecture.md's OutpostNode caveat, and the
  // approved plan's explicit scope cut on hand-rolled multi-hop logic).
  g_reticulum.transport_enabled(true);
  g_reticulum.probe_destination_enabled(true);
  g_reticulum.start();

  // Diagnostic canary — isolates "LittleFS mount/path handling is broken"
  // from "something Identity-specific is broken" (identity hash changing
  // across reboots during hardware bring-up — see AGENT_HANDOFF.md).
  {
    RNS::Bytes canary_out("hello");
    size_t wrote = RNS::Utilities::OS::write_file("/canary.txt", canary_out);
    RNS::Bytes canary_in;
    size_t read = RNS::Utilities::OS::read_file("/canary.txt", canary_in);
    Serial.printf("canary: wrote=%u read=%u match=%d\n", (unsigned)wrote,
                  (unsigned)read, canary_in == canary_out);
  }

  g_identity = RNS::Identity::from_file(IDENTITY_PATH);
  if (!g_identity) {
    Serial.println("No saved identity — generating a new one");
    g_identity = RNS::Identity();
    bool saved = g_identity.to_file(IDENTITY_PATH);
    Serial.printf("identity to_file() -> %d\n", saved);
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
  g_destination.announce();

  Serial.print("Outpost Reticulum destination: ");
  Serial.println(g_destination.hash().toHex().c_str());
}

// -- Corkboard sync (BOARD_SYNC over a plain Reticulum packet — matches
//    server/transports/reticulum.py's ReticulumTransport, which sends and
//    receives single RNS.Packet()s to/from a SINGLE destination, not a
//    Link session) --

static bool resolve_station(RNS::Bytes& station_hash) {
  static const char* hex = WAYPOST_STATION_DEST_HASH;
  if (strlen(hex) != 32) {
    g_status = "Station destination not configured — set WAYPOST_STATION_DEST_HASH "
               "in platformio.ini to Station's printed destination hash.";
    return false;
  }
  station_hash.assignHex(hex);
  if (station_hash.size() != 16) {
    g_status = "WAYPOST_STATION_DEST_HASH is not a valid 32-hex-char destination hash.";
    return false;
  }
  return true;
}

static bool wait_for_path(const RNS::Bytes& station_hash, uint32_t timeout_ms) {
  if (RNS::Transport::has_path(station_hash)) return true;
  RNS::Transport::request_path(station_hash);
  uint32_t start = millis();
  while (millis() - start < timeout_ms) {
    g_reticulum.loop();
    if (RNS::Transport::has_path(station_hash)) return true;
    delay(50);
  }
  return false;
}

// Shared by refresh_board() and claim_with_station(): resolve Station's
// configured hash, wait for a path, recall its identity, build the OUT
// destination. Sets g_status and returns false on any failure.
static bool connect_to_station(RNS::Destination& out_dest, const char* verb) {
  RNS::Bytes station_hash;
  if (!resolve_station(station_hash)) return false;

  if (!wait_for_path(station_hash, 8000)) {
    g_status = String("No path to Station yet — is Station's radio on and has it "
                       "announced since this Outpost booted? ") +
               verb;
    return false;
  }

  RNS::Identity station_identity = RNS::Identity::recall(station_hash);
  if (!station_identity) {
    g_status = String("Station's identity isn't known yet (no announce received). ") + verb;
    return false;
  }

  out_dest = RNS::Destination(
      station_identity,
      RNS::Type::Destination::OUT,
      RNS::Type::Destination::SINGLE,
      WAYPOST_APP_NAME,
      WAYPOST_ASPECT);
  return true;
}

// Shared send/wait/decode/rid-check for a single request→reply exchange.
// Sets g_status and returns false on any failure (timeout, malformed
// reply, rid mismatch, explicit error) — the caller only has to handle
// its own success path.
static bool send_and_await_reply(
    const RNS::Destination& dest,
    const RNS::Bytes& payload,
    const std::string& expected_rid,
    waylink::SyncReplyResult& result,
    const char* verb) {
  g_reply_pending = false;
  RNS::Packet pkt(dest, payload);
  pkt.send();

  uint32_t start = millis();
  while (millis() - start < 5000) {
    g_reticulum.loop();
    if (g_reply_pending) break;
    delay(20);
  }

  if (!g_reply_pending) {
    g_status = String("Request sent but Station didn't reply in time. ") + verb;
    return false;
  }
  g_reply_pending = false;

  if (!waylink::decode_sync_reply(g_reply_bytes.data(), g_reply_bytes.size(), result) ||
      !result.parsed) {
    g_status = String("Station's reply was malformed. ") + verb;
    return false;
  }
  if (result.rid != expected_rid) {
    g_status = String("Got a reply that doesn't match this request. ") + verb;
    return false;
  }
  if (result.error) {
    g_status = "Station reported an error: " + String(result.error_msg.c_str());
    return false;
  }
  if (!result.ok) {
    g_status = String("Station did not confirm the request. ") + verb;
    return false;
  }
  return true;
}

static void refresh_board() {
  RNS::Destination station_destination({RNS::Type::NONE});
  if (!connect_to_station(station_destination, "Showing cached board.")) return;

  std::vector<waylink::OutgoingNote> outgoing;
  for (const auto& n : g_notes) {
    if (n.synced) continue;
    waylink::OutgoingNote on;
    on.id = n.id;
    on.body = n.body;
    on.signature = n.signature;
    on.has_signature = n.has_signature;
    outgoing.push_back(on);
  }

  std::string mid = waylink::new_hex_id();
  std::string rid = waylink::new_hex_id();
  RNS::Bytes payload = waylink::encode_board_sync_request(
      WAYPOST_OUTPOST_ID, STATION_NODE_ID, mid, rid, /*ttl=*/8,
      /*display_name=*/nullptr, outgoing);

  waylink::SyncReplyResult result;
  if (!send_and_await_reply(station_destination, payload, rid, result,
                             "Showing cached board.")) {
    return;
  }

  for (auto& n : g_notes) {
    if (!n.synced) n.synced = true;
  }
  size_t received = 0;
  for (const auto& p : result.pending) {
    if (has_note(p.id)) continue;
    evict_if_full();
    Note n;
    n.id = p.id;
    n.body = p.body;
    n.signature = p.signature;
    n.has_signature = p.has_signature;
    n.synced = true;  // Station-composed notes arrive already-synced, by definition
    g_notes.push_back(std::move(n));
    received++;
  }

  g_status = "Synced with Station — " + String((unsigned)outgoing.size()) +
             " note(s) sent, " + String((unsigned)received) + " received.";
}

// -- Claiming: teach Station this Outpost's destination hash --

static String g_claim_status = "Not yet claimed by a Station.";

static void claim_with_station(const std::string& code) {
  RNS::Destination station_destination({RNS::Type::NONE});
  if (!connect_to_station(station_destination, "Try again in a moment.")) {
    g_claim_status = g_status;
    return;
  }

  std::string mid = waylink::new_hex_id();
  std::string rid = waylink::new_hex_id();
  std::string own_hash = g_destination.hash().toHex();
  RNS::Bytes payload = waylink::encode_outpost_claim_request(
      WAYPOST_OUTPOST_ID, STATION_NODE_ID, mid, rid, /*ttl=*/8, code, own_hash,
      /*display_name=*/nullptr);

  waylink::SyncReplyResult result;
  if (!send_and_await_reply(station_destination, payload, rid, result,
                             "Try again in a moment.")) {
    g_claim_status = g_status;
    return;
  }

  g_claim_status = "Claimed! Station now knows this Outpost as \"" +
                    String(WAYPOST_OUTPOST_ID) + "\".";
}

// -- Web UI --

static void send_redirect_home() {
  g_server.sendHeader("Location", "/", true);
  g_server.send(303, "text/plain", "");
}

static void handle_root() {
  String body = "<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<title>The Outpost</title>"
                "<style>body{font-family:sans-serif;max-width:640px;margin:1.5rem auto;"
                "padding:0 1rem;background:#faf7f0;color:#222}"
                "textarea,input{width:100%;box-sizing:border-box;margin:.25rem 0;"
                "font-family:inherit;font-size:1rem}"
                ".note{border:1px solid #d8cfae;border-radius:6px;padding:.6rem .8rem;"
                "margin:.6rem 0;background:#fffdf7}"
                ".sig{color:#666;font-size:.85rem;margin-top:.3rem}"
                ".status{color:#555;font-size:.9rem}"
                "button{padding:.5rem 1rem;font-size:1rem}</style></head><body>";
  body += "<h1>The Outpost</h1>";
  body += "<p>Leave a public note here. It stays on this Outpost and gets backed up "
          "to Station when a radio path exists. Anyone can read what's posted.</p>";
  body += "<p class='status'>" + g_status + "</p>";
  body += "<p><a href='/refresh'>Refresh / sync with Station</a> &middot; "
          "<a href='/claim'>Pair with Station</a></p>";
  body += "<form method='POST' action='/post'>";
  body += "<textarea name='body' rows='3' maxlength='" + String((unsigned)MAX_BODY) +
          "' placeholder='Note (bear sighting, trail closure, ...)' required></textarea>";
  body += "<input name='signature' maxlength='" + String((unsigned)MAX_SIGNATURE) +
          "' placeholder='Signature (optional, e.g. a name or trail handle)'>";
  body += "<button type='submit'>Post</button></form><hr>";

  if (g_notes.empty()) {
    body += "<p>No notes yet.</p>";
  } else {
    for (auto it = g_notes.rbegin(); it != g_notes.rend(); ++it) {
      body += "<div class='note'>" + html_escape(it->body);
      if (it->has_signature && !it->signature.empty()) {
        body += "<div class='sig'>&mdash; " + html_escape(it->signature) + "</div>";
      }
      if (!it->synced) {
        body += "<div class='sig'>(not yet synced to Station)</div>";
      }
      body += "</div>";
    }
  }
  body += "</body></html>";
  g_server.send(200, "text/html", body);
}

static void handle_post() {
  String body_arg = g_server.hasArg("body") ? g_server.arg("body") : "";
  String sig_arg = g_server.hasArg("signature") ? g_server.arg("signature") : "";
  body_arg.trim();
  sig_arg.trim();

  if (body_arg.length() == 0) {
    g_status = "Note can't be empty.";
    send_redirect_home();
    return;
  }
  if (body_arg.length() > MAX_BODY) {
    g_status = "Note too long (max " + String((unsigned)MAX_BODY) + " characters).";
    send_redirect_home();
    return;
  }
  if (sig_arg.length() > MAX_SIGNATURE) {
    g_status = "Signature too long (max " + String((unsigned)MAX_SIGNATURE) + " characters).";
    send_redirect_home();
    return;
  }

  evict_if_full();
  Note n;
  n.id = waylink::new_hex_id();
  n.body = std::string(body_arg.c_str());
  if (sig_arg.length() > 0) {
    n.signature = std::string(sig_arg.c_str());
    n.has_signature = true;
  }
  n.synced = false;
  g_notes.push_back(std::move(n));

  g_status = "Note posted locally. Hit Refresh to send it to Station when you can.";
  send_redirect_home();
}

static void handle_refresh() {
  refresh_board();
  send_redirect_home();
}

static void handle_claim_get() {
  String body = "<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<title>Pair with Station</title>"
                "<style>body{font-family:sans-serif;max-width:640px;margin:1.5rem auto;"
                "padding:0 1rem;background:#faf7f0;color:#222}"
                "input{width:100%;box-sizing:border-box;margin:.25rem 0;"
                "font-family:inherit;font-size:1.2rem;letter-spacing:.15em}"
                ".status{color:#555;font-size:.9rem}"
                ".hash{font-family:monospace;font-size:.85rem;word-break:break-all;color:#666}"
                "button{padding:.5rem 1rem;font-size:1rem}</style></head><body>";
  body += "<h1>Pair with Station</h1>";
  body += "<p>Generate a claim code on Station's Corkboard page, then enter it here. "
          "This teaches Station how to reach this Outpost — needed once, before "
          "Refresh can actually sync.</p>";
  body += "<p class='status'>" + g_claim_status + "</p>";
  body += "<form method='POST' action='/claim'>";
  body += "<input name='code' maxlength='12' placeholder='Claim code' autofocus required>";
  body += "<button type='submit'>Claim</button></form>";
  body += "<p class='hash'>This Outpost's own address: " +
          String(g_destination.hash().toHex().c_str()) + "</p>";
  body += "<p><a href='/'>Back to the board</a></p>";
  body += "</body></html>";
  g_server.send(200, "text/html", body);
}

static void handle_claim_post() {
  String code_arg = g_server.hasArg("code") ? g_server.arg("code") : "";
  code_arg.trim();
  if (code_arg.length() == 0) {
    g_claim_status = "Enter a code.";
  } else {
    claim_with_station(std::string(code_arg.c_str()));
  }
  g_server.sendHeader("Location", "/claim", true);
  g_server.send(303, "text/plain", "");
}

static void web_setup() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WAYPOST_AP_SSID);
  Serial.print("AP up: ");
  Serial.print(WAYPOST_AP_SSID);
  Serial.print(" @ ");
  Serial.println(WiFi.softAPIP());

  g_server.on("/", HTTP_GET, handle_root);
  g_server.on("/post", HTTP_POST, handle_post);
  g_server.on("/refresh", HTTP_GET, handle_refresh);
  g_server.on("/claim", HTTP_GET, handle_claim_get);
  g_server.on("/claim", HTTP_POST, handle_claim_post);
  g_server.begin();
}

void setup() {
  Serial.begin(115200);
  uint32_t start = millis();
  while (!Serial && millis() - start < 3000) delay(10);

  RNS::loglevel(RNS::LOG_NOTICE);

  pinMode(PIN_VEXT, OUTPUT);
  digitalWrite(PIN_VEXT, LOW);
  delay(80);
  oled_init();
  oled_splash();

  reticulum_setup();
  web_setup();

  Serial.println("Waypost Outpost ready.");
}

void loop() {
  g_server.handleClient();
  g_reticulum.loop();
}
