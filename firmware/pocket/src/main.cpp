/*
 * Waypost Scout — LilyGO T-Deck (M7).
 *
 * Product: Waypost Scout. Internal device class: Pocket — see docs/naming.md.
 *
 * A Cybiko-style handheld: a home launcher and apps (Dispatch chat,
 * Fieldbook wiki, Trailhead pages, Signal), all talking to Station over
 * microReticulum on the SX1262 LoRa radio via Waylink RPC.
 *
 *   main.cpp          bring-up + event loop
 *   station_link.*    Reticulum, identity, request/reply with retries
 *   input.*           keyboard + trackball -> events
 *   ui.*              TFT drawing helpers
 *   reader.*          chunked text reader (Fieldbook, Trailhead)
 *   app*.cpp          the apps
 */

// <string> before anything pulling in microStore (its headers assume it).
#include <string>
#include <utility>
#include <vector>

#include <Arduino.h>
#include <SPI.h>

#include "account.h"
#include "app.h"
#include "certs.h"
#include "contacts.h"
#include "input.h"
#include "kdf.h"
#include "station_link.h"
#include "store.h"
#include "sync.h"
#include "ui.h"
#include "utilities.h"
#include "scout_logo.h"
#include <microReticulum.h>

static void board_power_on() {
  // Peripheral power on. Not power-cycled: cutting it also restarts the
  // keyboard's own controller, which then didn't answer (keyboard dead,
  // 2026-10-05). The frozen-logo-after-reset problem was the shared SPI
  // bus, fixed in spi_bus.h. LilyGO's examples give the keyboard
  // controller 500 ms to start.
  pinMode(BOARD_POWERON, OUTPUT);
  digitalWrite(BOARD_POWERON, HIGH);
  delay(500);
  // Display, LoRa radio, and SD slot share one SPI bus. Deselect the radio
  // and SD card before the display is used (LilyGO's T-Deck examples do the
  // same); an undriven chip-select floats.
  pinMode(BOARD_SDCARD_CS, OUTPUT);
  digitalWrite(BOARD_SDCARD_CS, HIGH);
  pinMode(RADIO_CS_PIN, OUTPUT);
  digitalWrite(RADIO_CS_PIN, HIGH);
}

static const uint32_t kIdleLockMs = 5UL * 60UL * 1000UL;  // PIN lock after no keys
static const uint32_t kIdleDimMs = 60UL * 1000UL;          // dim the screen
static const uint32_t kIdleOffMs = 3UL * 60UL * 1000UL;    // then switch it off
static const uint8_t kDimLevel = 3;
static uint32_t g_last_input = 0;     // last key (the lock timer)
static uint32_t g_last_activity = 0;  // last key, or something worth showing (the screen)

// Something arrived that the person should see: light the screen. Doesn't
// postpone the PIN lock.
static void wake() { g_last_activity = millis(); }

// Boot screen: the Waypost Scout logo (src/scout_logo.h, 320x240) with a
// slim progress bar under the tagline, so a slow step never looks frozen.
static const uint32_t kSplashMinMs = 5000;  // logo stays up at least this long
static const int kBarX = 60, kBarY = 229, kBarW = ui::kWidth - 120, kBarH = 5;
static const uint16_t kBarTrack = ui::rgb(0xdf, 0xe5, 0xe0);
static const uint16_t kBarFill = ui::rgb(0x0b, 0x3a, 0x2a);  // the logo's compass green

static void draw_splash() {
  auto& t = ui::tft();
  for (int y = 0; y < SCOUT_LOGO_HEIGHT; y++) {
    for (int x = 0; x < SCOUT_LOGO_WIDTH; x++) {
      t.drawPixel(x, y, pgm_read_word(&SCOUT_LOGO[y * SCOUT_LOGO_WIDTH + x]));
    }
  }
  ui::mark_dirty();
  ui::present();
}

static void draw_boot_progress(const char* step, int percent) {
  auto& t = ui::tft();
  t.fillRect(0, kBarY - 3, ui::kWidth, ui::kHeight - (kBarY - 3), SCOUT_LOGO_BG);
  if (percent < 0) {
    // Failure: say so in place of the bar.
    t.setTextDatum(MC_DATUM);
    t.setTextColor(ui::kError, SCOUT_LOGO_BG);
    t.drawString(step, ui::kWidth / 2, kBarY + 2, 2);
    t.setTextDatum(TL_DATUM);
  } else {
    t.fillRoundRect(kBarX, kBarY, kBarW, kBarH, 2, kBarTrack);
    if (percent > 0) {
      t.fillRoundRect(kBarX, kBarY, kBarW * percent / 100, kBarH, 2, kBarFill);
    }
  }
  ui::mark_dirty(0, kBarY - 3, ui::kWidth, ui::kHeight - (kBarY - 3));
  ui::present();
}

void setup() {
  Serial.begin(115200);
  // Native USB serial: with the cable in but nobody reading the port, each
  // write otherwise blocks until a timeout, and microReticulum logs dozens
  // of lines at boot (seen: 26 s to reach LoRa init). Drop instead.
  Serial.setTxTimeoutMs(0);
  uint32_t serial_start = millis();
  while (!Serial && millis() - serial_start < 1000) delay(10);

  board_power_on();
  delay(50);
  ui::init();
  draw_splash();
  uint32_t splash_start = millis();
  draw_boot_progress("", 2);
  input::init();

  Serial.println();
  Serial.println("Waypost Scout");
  // Storage now; the radio starts on a background task, so the apps don't
  // wait for it (a cold power-on once took ~3 minutes to bring it up).
  if (!station_link::mount_storage()) {
    draw_boot_progress("Storage failed to mount - check the board", -1);
    return;
  }
  // Files first, radio after: storage isn't safe for two tasks at once.
  account::load();
  contacts::load();
  store::load();
  apps::beacon_load();
  certs::load();
  certs::self_test();
#ifdef WAYPOST_KDF_SELFTEST
  {  // one-off: server/tests/test_identity_keys.py vector, and how long it takes here
    uint32_t t0 = millis();
    std::string seed = kdf::identity_seed("Basecamp", "blue canoe river");
    char hex[65] = {0};
    for (size_t i = 0; i < seed.size(); i++) snprintf(hex + 2 * i, 3, "%02x", static_cast<uint8_t>(seed[i]));
    Serial.printf("kdf: %s in %lu ms (%s)\n", hex, static_cast<unsigned long>(millis() - t0),
                  strcmp(hex, "0bfde6e3b8b2a6f55eb9e13e94c483df0a5feb350e939a840240c8e241d2c2e6") == 0 ? "matches" : "MISMATCH");
  }
#endif
  ui::set_unread(store::unread_total());
  station_link::start_radio();
  // Show the logo for its minimum time; the bar just marks the time.
  while (millis() - splash_start < kSplashMinMs) {
    draw_boot_progress("", static_cast<int>((millis() - splash_start) * 100 / kSplashMinMs));
    delay(100);
  }
  Serial.printf("boot: home after %lu ms (radio %s)\n",
                static_cast<unsigned long>(millis() - splash_start),
                station_link::ready() ? "ready" : "still starting");
  station_link::set_busy_hooks(ui::busy_tick, ui::busy_clear);
  station_link::set_wait_hook(input::pump);  // keys typed during a request are kept
  g_last_input = g_last_activity = millis();
  if (!account::paired()) {
    apps::open(apps::login_app());  // adopted automatically if Station already knows us
  } else {
    apps::home();
    apps::lock();  // no-op without a PIN
  }
}


// Someone is typing (or rolling the trackball): background network work
// waits, so the loop stays free to handle keys. Each request blocks the
// loop for a second or more, and the keyboard controller holds only one
// key — typing a PIN during a sync lost keys (reported 2026-10-05).
static const uint32_t kTypingQuietMs = 20000;
static bool typing() {
  uint32_t last = input::last_activity();
  return last != 0 && millis() - last < kTypingQuietMs;
}

void loop() {
  station_link::loop();
  store::loop();  // writes saved-message changes once storage is free
  if (!typing()) certs::loop();  // offline identity: fetch/refresh certificates, save

  // Once the radio task finishes (or fails), keep its timing for the
  // Signal app — serial output is lost when nobody is reading the port.
  static bool boot_timing_saved = false;
  if (!boot_timing_saved && (station_link::ready() || station_link::failed())) {
    boot_timing_saved = true;
    std::string t = station_link::boot_timing();
    Serial.printf("boot timing: %s\n", t.c_str());
    ui::reinit_panel();  // the radio is done with the bus: start the panel afresh
    RNS::Utilities::OS::write_file("/waypost_lastboot", RNS::Bytes(t));
  }

  waylink::IncomingChatMessage msg;
  while (station_link::pop_incoming(msg)) {
    apps::deliver_chat(msg);
    wake();
  }
  waylink::Reply event;
  while (station_link::pop_event(event)) {
    if (event.envelope.text("op") == "BEACON_ALERT") apps::beacon_event(event.payload());
    else if (event.envelope.text("svc") == "SYNC") peersync::handle(event);  // a peer syncing with us
  }
  if (apps::beacon_showing()) wake();  // an alert keeps the screen lit
  apps::beacon_save();                  // saved alerts, once storage is free

  App* app = apps::current();
  if (app) {
    input::Event e = input::poll();
    if (e.kind != input::Kind::None) {
      bool was_dark = ui::brightness() == 0;
      g_last_input = g_last_activity = millis();
      // The key that wakes a dark screen only wakes it.
      if (!was_dark) app->on_event(e);
    } else if (millis() - g_last_input >= kIdleLockMs && account::has_pin() && !apps::locked() &&
               !apps::beacon_showing()) {
      apps::lock();
    }
    // on_event may have switched apps.
    apps::current()->tick();
  }

  uint32_t idle = millis() - g_last_activity;
  ui::set_brightness(idle >= kIdleOffMs ? 0 : idle >= kIdleDimMs ? kDimLevel : ui::kBrightnessMax);

  // Learns/confirms which account this Scout belongs to once Station is in
  // reach (rate-limited inside).
  if (!apps::locked() && !typing()) apps::check_identity();

  // Fetch missed messages each time Station comes (back) into reach, and
  // every few minutes while it's in reach: a push whose frames were lost,
  // or whose delivery ack was lost, stays pending on Station until a
  // MSG_SYNC collects it (duplicates are dropped by message id).
  static bool station_was_known = false;
  static uint32_t last_catch_up = 0;
  const uint32_t kCatchUpEveryMs = 3UL * 60UL * 1000UL;
  // Look for Station when its path isn't known (throttled to every 30 s
  // inside). Without this a locked Scout only found Station at Station's
  // next announce, which after a Station restart could be a long wait.
  station_link::seek_station();
  bool known = station_link::station_known();
  bool came_back = known && !station_was_known &&
                   (last_catch_up == 0 || millis() - last_catch_up > 60000);
  bool periodic = known && last_catch_up != 0 && millis() - last_catch_up > kCatchUpEveryMs;
  if ((came_back || periodic) && account::paired() && !typing()) {
    last_catch_up = millis();
    apps::catch_up_chat();  // saved on the Scout, so fine while locked too
    // A Beacon raised while we were off or away — shown even when locked.
    apps::check_beacon();
  }
  if (!typing()) station_was_known = known;  // a return while typing is caught up afterwards

  // Queued messages go out as soon as Station is in reach (one per loop).
  if (!typing()) {
    if (known && account::paired()) apps::flush_outbox();
    // Peer sync (D4): Station every few minutes, Outposts and contacts' Scouts in range.
    peersync::loop();
  }

  static uint32_t last_status = 0;
  if (millis() - last_status >= 1000) {
    last_status = millis();
    ui::set_station_ok(station_link::station_known());
  }

  ui::present();

  delay(5);
}
