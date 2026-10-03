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

static void draw_splash(const char* status) {
  auto& t = ui::tft();
  t.fillScreen(TFT_BLACK);
  t.drawXBitmap((ui::kWidth - WAYPOST_MARK_WIDTH) / 2, 50, WAYPOST_MARK_BITS, WAYPOST_MARK_WIDTH,
                WAYPOST_MARK_HEIGHT, TFT_WHITE);
  t.setTextDatum(MC_DATUM);
  t.setTextColor(TFT_WHITE, TFT_BLACK);
  t.drawString("WAYPOST SCOUT", ui::kWidth / 2, 120, 4);
  t.setTextColor(TFT_DARKGREY, TFT_BLACK);
  t.drawString(status, ui::kWidth / 2, 160, 2);
  t.setTextDatum(TL_DATUM);
}

void setup() {
  Serial.begin(115200);
  uint32_t serial_start = millis();
  while (!Serial && millis() - serial_start < 3000) delay(10);

  board_power_on();
  delay(50);
  ui::init();
  draw_splash("Starting radio...");
  input::init();

  Serial.println();
  Serial.println("Waypost Scout");
  if (!station_link::setup()) {
    draw_splash("Radio failed to start - check the board");
    return;
  }
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

  delay(5);
}
