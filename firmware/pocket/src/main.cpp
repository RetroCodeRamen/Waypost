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

#include "app.h"
#include "input.h"
#include "station_link.h"
#include "ui.h"
#include "utilities.h"
#include "waypost_mark.h"

static void board_power_on() {
  pinMode(BOARD_POWERON, OUTPUT);
  digitalWrite(BOARD_POWERON, HIGH);
}

static void draw_splash() {
  auto& t = ui::tft();
  t.fillScreen(ui::kBg);
  t.drawXBitmap((ui::kWidth - WAYPOST_MARK_WIDTH) / 2, 40, WAYPOST_MARK_BITS, WAYPOST_MARK_WIDTH,
                WAYPOST_MARK_HEIGHT, ui::kText);
  t.setTextDatum(MC_DATUM);
  t.setTextColor(ui::kText, ui::kBg);
  t.drawString("WAYPOST SCOUT", ui::kWidth / 2, 110, 4);
  t.setTextDatum(TL_DATUM);
  ui::mark_dirty();
  ui::present();
}

// Boot progress under the splash: what's happening now + a bar, so a slow
// step never looks like a freeze.
static void draw_boot_progress(const char* step, int percent) {
  auto& t = ui::tft();
  const int bar_x = 60, bar_y = 150, bar_w = ui::kWidth - 120, bar_h = 8;
  t.fillRect(0, bar_y - 26, ui::kWidth, 24, ui::kBg);
  t.setTextDatum(MC_DATUM);
  t.setTextColor(percent < 0 ? ui::kWarn : ui::kTextDim, ui::kBg);
  t.drawString(step, ui::kWidth / 2, bar_y - 14, 2);
  t.setTextDatum(TL_DATUM);
  t.drawRect(bar_x, bar_y, bar_w, bar_h, ui::kMuted);
  if (percent > 0) {
    t.fillRect(bar_x + 1, bar_y + 1, (bar_w - 2) * percent / 100, bar_h - 2, ui::kLive);
  }
  ui::mark_dirty(0, bar_y - 26, ui::kWidth, bar_h + 26);
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
  draw_boot_progress("Starting up", 5);
  input::init();

  Serial.println();
  Serial.println("Waypost Scout");
  if (!station_link::setup(draw_boot_progress)) {
    draw_boot_progress("Radio failed to start - check the board", -1);
    return;
  }
  draw_boot_progress("Ready", 100);
  station_link::set_busy_hooks(ui::busy_tick, ui::busy_clear);
  apps::home();
}

void loop() {
  station_link::loop();

  waylink::IncomingChatMessage msg;
  while (station_link::pop_incoming(msg)) apps::deliver_chat(msg);

  App* app = apps::current();
  if (app) {
    input::Event e = input::poll();
    if (e.kind != input::Kind::None) app->on_event(e);
    // on_event may have switched apps.
    apps::current()->tick();
  }

  static uint32_t last_status = 0;
  if (millis() - last_status >= 1000) {
    last_status = millis();
    ui::set_station_ok(station_link::station_known());
  }

  ui::present();

  delay(5);
}
