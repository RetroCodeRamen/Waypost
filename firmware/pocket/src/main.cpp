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

#include <Arduino.h>
#include <SPI.h>

#include "account.h"
#include "app.h"
#include "contacts.h"
#include "input.h"
#include "station_link.h"
#include "ui.h"
#include "utilities.h"
#include "scout_logo.h"

static void board_power_on() {
  pinMode(BOARD_POWERON, OUTPUT);
  digitalWrite(BOARD_POWERON, HIGH);
  // Display, LoRa radio, and SD slot share one SPI bus. Deselect the radio
  // and SD card before the display is used (LilyGO's T-Deck examples do the
  // same); an undriven chip-select floats.
  pinMode(BOARD_SDCARD_CS, OUTPUT);
  digitalWrite(BOARD_SDCARD_CS, HIGH);
  pinMode(RADIO_CS_PIN, OUTPUT);
  digitalWrite(RADIO_CS_PIN, HIGH);
}

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
  draw_boot_progress("Starting up", 5);
  input::init();

  Serial.println();
  Serial.println("Waypost Scout");
  if (!station_link::setup(draw_boot_progress)) {
    draw_boot_progress("Radio failed to start - check the board", -1);
    return;
  }
  draw_boot_progress("Ready", 100);
  // Let the logo be seen even when boot is quick (~3 s).
  while (millis() - splash_start < kSplashMinMs) {
    station_link::loop();
    delay(10);
  }
  Serial.printf("boot: home after %lu ms\n", static_cast<unsigned long>(millis() - splash_start));
  station_link::set_busy_hooks(ui::busy_tick, ui::busy_clear);
  account::load();
  contacts::load();
  if (!account::paired()) {
    apps::open(apps::pairing_app());  // adopted automatically if Station already knows us
  } else {
    apps::home();
    apps::lock();  // no-op without a PIN
  }
}

static const uint32_t kIdleLockMs = 5UL * 60UL * 1000UL;

void loop() {
  station_link::loop();

  waylink::IncomingChatMessage msg;
  while (station_link::pop_incoming(msg)) apps::deliver_chat(msg);

  App* app = apps::current();
  if (app) {
    static uint32_t last_input = millis();
    input::Event e = input::poll();
    if (e.kind != input::Kind::None) {
      last_input = millis();
      app->on_event(e);
    } else if (millis() - last_input >= kIdleLockMs && account::has_pin() && !apps::locked()) {
      apps::lock();
    }
    // on_event may have switched apps.
    apps::current()->tick();
  }

  // Learns/confirms which account this Scout belongs to once Station is in
  // reach (rate-limited inside).
  if (!apps::locked()) apps::check_identity();

  // Each time Station comes (back) into reach: fetch missed messages.
  static bool station_was_known = false;
  static uint32_t last_catch_up = 0;
  bool known = station_link::station_known();
  if (known && !station_was_known && account::paired() && !apps::locked() &&
      (last_catch_up == 0 || millis() - last_catch_up > 60000)) {
    last_catch_up = millis();
    apps::catch_up_chat();
  }
  station_was_known = known;

  static uint32_t last_status = 0;
  if (millis() - last_status >= 1000) {
    last_status = millis();
    ui::set_station_ok(station_link::station_known());
  }

  ui::present();

  delay(5);
}
