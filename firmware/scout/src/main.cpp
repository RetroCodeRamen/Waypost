// Waypost Scout — LilyGO T-Deck. Rebuilt 2026-10-05
// (docs/scout-firmware-architecture.md).
//
// A Cybiko-style handheld: a home launcher and apps (Dispatch, Beacon,
// Fieldbook, Trailhead, Signal, Settings) talking to Station — and to
// Outposts and other Scouts — over microReticulum on the LoRa radio.
//
// Tasks:
//   net    (core 0)  Reticulum, the radio, every packet          net.*
//   ui     (core 1)  keys, apps, all app state, the screen       here, app_*.cpp
//   crypto (core 1)  password key, PIN seal                      tasks.*
//   sync   (core 1)  peer sync                                   sync.*
// The UI task never waits on the network or on slow crypto: requests take a
// callback (rpc::ask), workers post their results back.
//
//   board.*    bring-up order          bus.*      the shared SPI bus lock
//   display.*  LovyanGFX + canvas      ui.*       drawing kit
//   input.*    keyboard, trackball     radio.*    non-blocking LoRa driver
//   store.*    messages on flash       certs.*    identity + certificates
#include <string>

#include <Arduino.h>

#include "account.h"
#include "app.h"
#include "board.h"
#include "certs.h"
#include "contacts.h"
#include "display.h"
#include "input.h"
#include "net.h"
#include "scout_logo.h"
#include "store.h"
#include "sync.h"
#include "tasks.h"
#include "ui.h"

namespace {

constexpr uint32_t kFrameMs = 33;                         // ~30 frames a second
constexpr uint32_t kIdleLockMs = 5UL * 60UL * 1000UL;     // PIN lock after no keys
constexpr uint32_t kIdleDimMs = 60UL * 1000UL;            // dim the screen
constexpr uint32_t kIdleOffMs = 3UL * 60UL * 1000UL;      // then switch it off
constexpr uint8_t kDimLevel = 3;
constexpr uint32_t kCatchUpEveryMs = 3UL * 60UL * 1000UL;
constexpr uint32_t kSplashMs = 2500;

uint32_t g_last_input = 0;     // last key (the lock timer)
uint32_t g_last_activity = 0;  // last key, or something worth showing (the screen)

// Something arrived that the person should see: light the screen. Doesn't
// postpone the PIN lock.
void wake() { g_last_activity = millis(); }

// -- boot screen ------------------------------------------------------------------

constexpr int kBarX = 60, kBarY = 229, kBarW = ui::kWidth - 120, kBarH = 5;

void draw_splash(int percent) {
  auto& t = ui::tft();
  if (percent == 0) {
    t.pushImage(0, 0, SCOUT_LOGO_WIDTH, SCOUT_LOGO_HEIGHT, SCOUT_LOGO);
    ui::mark_dirty();
  }
  t.fillRoundRect(kBarX, kBarY, kBarW, kBarH, 2, ui::rgb(0xdf, 0xe5, 0xe0));
  if (percent > 0) t.fillRoundRect(kBarX, kBarY, kBarW * percent / 100, kBarH, 2, ui::rgb(0x0b, 0x3a, 0x2a));
  ui::mark_dirty(kBarX, kBarY, kBarW, kBarH);
}

// -- network events -----------------------------------------------------------------

void handle_incoming() {
  net::Incoming in;
  while (net::incoming(in)) {
    if (in.kind == net::Incoming::Chat) {
      apps::deliver_chat(in.chat);
      wake();
    } else if (in.event.envelope.text("op") == "BEACON_ALERT") {
      apps::beacon_event(in.event.payload());
    } else if (in.event.envelope.text("svc") == "SYNC") {
      peersync::handle(in.event);  // a peer syncing with us
    }
  }
  if (apps::beacon_showing()) wake();  // an alert keeps the screen lit
}

// Background work with Station and peers. Every piece is asynchronous; each
// keeps at most one request out.
void background() {
  store::loop();
  certs::loop();
  apps::beacon_save();
  if (!apps::locked()) apps::check_identity();

  // Fetch missed messages each time Station comes (back) into reach, and
  // every few minutes while it's in reach: a push whose frames or ack were
  // lost stays pending on Station until MSG_SYNC collects it (duplicates
  // are dropped by message id).
  static bool was_known = false;
  static uint32_t last_catch_up = 0;
  bool known = net::station_known();
  bool came_back = known && !was_known && (last_catch_up == 0 || millis() - last_catch_up > 60000);
  bool periodic = known && last_catch_up != 0 && millis() - last_catch_up > kCatchUpEveryMs;
  if ((came_back || periodic) && account::paired()) {
    last_catch_up = millis();
    apps::catch_up_chat();  // saved on the Scout, so fine while locked too
    apps::check_beacon();   // a Beacon raised while we were off or away
  }
  was_known = known;

  if (known && account::paired()) apps::flush_outbox();
  peersync::loop();
}

void handle_input() {
  App* app = apps::current();
  input::Event e;
  while (input::next(e)) {
    bool was_dark = ui::brightness() == 0;
    g_last_input = g_last_activity = millis();
    if (was_dark) continue;  // the key that wakes a dark screen only wakes it
    app->on_event(e);
    app = apps::current();  // on_event may have switched apps
  }
  if (millis() - g_last_input >= kIdleLockMs && account::has_pin() && !apps::locked() &&
      !apps::beacon_showing()) {
    apps::lock();
  }
}

void ui_task(void*) {
  tasks::set_ui_task();
  // Boot screen while the radio starts on its own task.
  uint32_t start = millis();
  for (int pct = 0; millis() - start < kSplashMs; pct = (millis() - start) * 100 / kSplashMs) {
    draw_splash(pct);
    display::flush();
    vTaskDelay(pdMS_TO_TICKS(50));
  }
  ui::init();
  ui::set_unread(store::unread_total());
  g_last_input = g_last_activity = millis();
  if (!account::paired()) {
    apps::open(apps::login_app());
  } else {
    apps::home();
    apps::lock();  // no-op without a PIN
  }

  uint32_t frame_at = millis(), second_at = millis(), frames = 0, worst = 0;
  for (;;) {
    uint32_t t0 = millis();
    tasks::drain();   // results from the workers
    rpc::poll();     // finished requests' callbacks
    handle_incoming();
    input::poll();
    handle_input();
    apps::current()->tick();
    background();

    static uint32_t status_at = 0;
    if (millis() - status_at >= 1000) {
      status_at = millis();
      ui::set_station_ok(net::station_known());
    }
    ui::animate(rpc::busy() > 0);
    uint32_t idle = millis() - g_last_activity;
    ui::set_brightness(idle >= kIdleOffMs ? 0 : idle >= kIdleDimMs ? kDimLevel : ui::kBrightnessMax);
    display::flush();

    frames++;
    worst = std::max<uint32_t>(worst, millis() - t0);
    if (millis() - second_at >= 60000) {
      Serial.printf("ui: %lu frames/min, slowest %lu ms, %d request(s) out\n",
                    static_cast<unsigned long>(frames), static_cast<unsigned long>(worst), net::pending());
      frames = worst = 0;
      second_at = millis();
    }
    // Next frame, or sooner if a worker posts something.
    frame_at += kFrameMs;
    int32_t left = static_cast<int32_t>(frame_at - millis());
    if (left <= 0) {
      frame_at = millis();
      left = 1;
    }
    tasks::wait(left);
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  // Native USB serial: with nobody reading the port, a write would block
  // until a timeout. Drop instead.
  Serial.setTxTimeoutMs(0);
  board::bring_up();
  display::init();
  draw_splash(0);
  display::flush();
  input::init();
  Serial.println("\nWaypost Scout");

  // Files first (the apps' own), then the tasks.
  net::mount_storage();
  account::load();
  contacts::load();
  store::load();
  apps::beacon_load();
  certs::load();
  certs::self_test();

  tasks::start_workers();
  net::start();
  xTaskCreatePinnedToCore(ui_task, "ui", 24576, nullptr, 3, nullptr, 1);
}

void loop() { vTaskDelete(nullptr); }  // the tasks do everything
