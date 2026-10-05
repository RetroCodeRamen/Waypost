// Waypost Scout — rebuilt firmware, milestone 1 (docs/scout-firmware-architecture.md).
//
// Two tasks and nothing else:
//   net (core 0)  Reticulum, the radio, every network job   — net.cpp
//   ui  (core 1)  keys, trackball, drawing, screen flushes  — here
// They share only net's command queue and status snapshot, and the SPI bus
// under one lock (bus.h). No apps yet: a test screen to prove the screen
// and keys stay smooth while the radio is busy (press F for a PING flood).
#include <string>

#include <Arduino.h>

#include "board.h"
#include "display.h"
#include "input.h"
#include "net.h"

namespace {

constexpr uint32_t kFrameMs = 33;  // ~30 frames a second

struct Colours {
  uint16_t bg, panel, text, dim, accent, ok, warn, bad;
};
Colours c;

// What the UI shows, kept by the UI task.
uint32_t g_frames = 0, g_fps = 0, g_frame_max_ms = 0;
std::string g_typed;
std::string g_last_key = "-";
uint32_t g_keys = 0, g_rolls = 0;

const char* kind_name(input::Kind k) {
  switch (k) {
    case input::Kind::Up: return "up";
    case input::Kind::Down: return "down";
    case input::Kind::Left: return "left";
    case input::Kind::Right: return "right";
    case input::Kind::Select: return "press";
    case input::Kind::Enter: return "enter";
    case input::Kind::Backspace: return "backspace";
    default: return "?";
  }
}

void handle(const input::Event& e) {
  if (e.kind == input::Kind::Char) {
    g_keys++;
    g_last_key = std::string("'") + e.ch + "'";
    char lower = static_cast<char>(tolower(e.ch));
    if (lower == 'f') net::send(net::Command::ToggleFlood);
    else if (lower == 'p') net::send(net::Command::Ping);
    else if (lower == 'a') net::send(net::Command::Announce);
    if (g_typed.size() >= 30) g_typed.erase(0, 1);
    g_typed += e.ch;
    return;
  }
  g_last_key = kind_name(e.kind);
  if (e.kind == input::Kind::Up || e.kind == input::Kind::Down || e.kind == input::Kind::Left ||
      e.kind == input::Kind::Right) {
    g_rolls++;
  } else {
    g_keys++;
  }
  if (e.kind == input::Kind::Backspace && !g_typed.empty()) g_typed.pop_back();
  if (e.kind == input::Kind::Enter) g_typed.clear();
  if (e.kind == input::Kind::Select) net::send(net::Command::Ping);
}

const char* stage_name(const net::Status& s) {
  switch (s.stage) {
    case net::Stage::Starting: return s.step;
    case net::Stage::Ready: return "ready";
    case net::Stage::Failed: return "FAILED";
  }
  return "?";
}

// The text part, redrawn only when what it shows changes.
std::string text_snapshot(const net::Status& s) {
  char buf[512];
  snprintf(buf, sizeof(buf),
           "%u|%u|%s|%s|%d|%d|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%.0f|%.1f|%u|%s|%s|%u|%u",
           g_fps, g_frame_max_ms, stage_name(s), s.dest, s.station_path, s.flooding, s.pings_sent,
           s.pings_ok, s.pings_lost, s.last_rtt_ms, s.loop_max_ms, s.radio.tx_packets,
           s.radio.rx_packets, s.radio.tx_frames, s.radio.rx_frames, s.radio.busy_backoffs,
           s.radio.last_rssi, s.radio.last_snr, s.radio.rx_errors + s.radio.tx_errors,
           g_last_key.c_str(), g_typed.c_str(), g_keys, g_rolls);
  return buf;
}

void draw_text(const net::Status& s) {
  auto& g = display::canvas();
  constexpr int kTop = 0, kBottom = 224;
  g.fillRect(0, kTop, board::kWidth, kBottom - kTop, c.bg);

  g.fillRect(0, 0, board::kWidth, 22, c.panel);
  g.setFont(&fonts::Font2);
  g.setTextColor(c.accent, c.panel);
  g.setCursor(6, 3);
  g.print("WAYPOST SCOUT");
  g.setTextColor(c.dim, c.panel);
  g.print("  rebuild test");

  g.setTextColor(c.text, c.bg);
  int y = 28;
  auto line = [&](uint16_t colour, const char* text) {
    g.setTextColor(colour, c.bg);
    g.setCursor(6, y);
    g.print(text);
    y += 17;
  };
  char b[96];
  snprintf(b, sizeof(b), "Screen  %u fps   slowest frame %u ms", g_fps, g_frame_max_ms);
  line(c.text, b);
  snprintf(b, sizeof(b), "Net     %s   slowest pass %u ms", stage_name(s), s.loop_max_ms);
  line(s.stage == net::Stage::Failed ? c.bad : (s.stage == net::Stage::Ready ? c.ok : c.warn), b);
  snprintf(b, sizeof(b), "Me      %.16s", s.dest[0] ? s.dest : "-");
  line(c.dim, b);
  snprintf(b, sizeof(b), "Station %s", s.station_path ? "path known" : "no path yet");
  line(s.station_path ? c.ok : c.warn, b);
  snprintf(b, sizeof(b), "Radio   tx %u/%u  rx %u/%u  busy %u  err %u", s.radio.tx_packets, s.radio.tx_frames, s.radio.rx_packets, s.radio.rx_frames, s.radio.busy_backoffs, s.radio.rx_errors + s.radio.tx_errors);
  line(c.text, b);
  snprintf(b, sizeof(b), "        last %.0f dBm  SNR %.1f", s.radio.last_rssi, s.radio.last_snr);
  line(c.dim, b);
  snprintf(b, sizeof(b), "PING    %u sent  %u ok  %u lost  %u ms%s", s.pings_sent, s.pings_ok, s.pings_lost, s.last_rtt_ms, s.flooding ? "  FLOOD" : "");
  line(s.flooding ? c.warn : c.text, b);
  snprintf(b, sizeof(b), "Keys    %u   rolls %u   last %s", g_keys, g_rolls, g_last_key.c_str());
  line(c.text, b);
  snprintf(b, sizeof(b), "> %s_", g_typed.c_str());
  line(c.accent, b);
  y += 4;
  snprintf(b, sizeof(b), "P ping   F flood on/off   A announce");
  line(c.dim, b);
  snprintf(b, sizeof(b), "press: ping   enter: clear");
  line(c.dim, b);
  display::mark(0, kTop, board::kWidth, kBottom - kTop);
}

// A block sweeping along the bottom every frame: if anything stalls the UI
// or the panel stops taking updates, it visibly stops or tears.
void draw_sweep() {
  auto& g = display::canvas();
  constexpr int kY = 228, kH = 10, kW = 40;
  g.fillRect(0, kY, board::kWidth, kH, c.panel);
  int x = (g_frames * 4) % (board::kWidth + kW) - kW;
  g.fillRect(x, kY, kW, kH, c.accent);
  display::mark(0, kY, board::kWidth, kH);
}

void ui_task(void*) {
  uint32_t second = millis(), frames_this_second = 0, worst = 0;
  std::string shown;
  TickType_t wake = xTaskGetTickCount();
  for (;;) {
    uint32_t t0 = millis();
    input::poll();
    input::Event e;
    while (input::next(e)) handle(e);

    net::Status s = net::status();
    std::string snap = text_snapshot(s);
    if (snap != shown) {
      draw_text(s);
      shown = snap;
    }
    draw_sweep();
    display::flush();

    g_frames++;
    frames_this_second++;
    worst = std::max<uint32_t>(worst, millis() - t0);
    if (millis() - second >= 1000) {
      g_fps = frames_this_second;
      g_frame_max_ms = worst;
      Serial.printf("ui: %u fps, slowest frame %u ms | net %s, pass max %u ms, tx %u rx %u busy %u\n",
                    g_fps, g_frame_max_ms, stage_name(s), s.loop_max_ms, s.radio.tx_packets,
                    s.radio.rx_packets, s.radio.busy_backoffs);
      frames_this_second = 0;
      worst = 0;
      second = millis();
    }
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(kFrameMs));
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  board::bring_up();
  display::init();
  c = {display::rgb(8, 20, 24),    display::rgb(16, 44, 52),  display::rgb(220, 232, 230),
       display::rgb(120, 150, 150), display::rgb(64, 200, 190), display::rgb(90, 210, 120),
       display::rgb(240, 190, 70),  display::rgb(240, 90, 80)};
  input::init();
  net::start();
  xTaskCreatePinnedToCore(ui_task, "ui", 16384, nullptr, 3, nullptr, 1);
}

void loop() { vTaskDelete(nullptr); }  // the two tasks do everything
