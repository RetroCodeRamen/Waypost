// Signal — this Scout's radio identity and its link to Station, with a PING.
#include <string>

#include <Arduino.h>

#include "app.h"
#include "tasks.h"
#include "ui.h"

#ifndef WAYPOST_STATION_DEST_HASH
#define WAYPOST_STATION_DEST_HASH ""
#endif

namespace {

class SignalApp : public App {
 public:
  const char* title() const override { return "Signal"; }

  void enter() override {
    ui::title_bar(title());
    ui::clear_body();
    draw();
  }

  void on_event(const input::Event& e) override {
    using input::Kind;
    if (e.kind == Kind::Left || e.kind == Kind::Backspace) {
      apps::home();
    } else if ((e.kind == Kind::Select || e.kind == Kind::Enter) && !_pinging) {
      ping();
    }
  }

  void tick() override {
    if (millis() - _drawn_at >= 1000) draw();  // radio counters, Station reach
  }

 private:
  void ping() {
    _pinging = true;
    uint32_t start = millis();
    rpc::ask("CORE", "PING", {},
              [this, start](net::Result r, waylink::Reply&) {
                _pinging = false;
                _pinged = true;
                _ping_result = r;
                _ping_ms = millis() - start;
                if (apps::current() == this) draw();
              },
              1, 15000);
    draw();
  }

  void draw() {
    _drawn_at = millis();
    net::Status s = net::status();
    std::string station = WAYPOST_STATION_DEST_HASH;
    ui::body_line(0, "This Scout", ui::kText);
    ui::body_line(1, "  node   " + (s.node_id.empty() ? std::string("-") : s.node_id));
    if (s.failed) {
      ui::body_line(2, "  radio  FAILED to start - restart the Scout", ui::kError);
    } else if (!s.ready) {
      ui::body_line(2, "  radio  starting...", ui::kWarn);
    } else {
      ui::body_line(2, "  dest   " + s.dest_hex.substr(0, 16) + "...");
    }
    char radio[96];
    snprintf(radio, sizeof(radio), "  radio  sent %u  heard %u  busy %u  last %.0f dBm",
             static_cast<unsigned>(s.radio.tx_packets), static_cast<unsigned>(s.radio.rx_packets),
             static_cast<unsigned>(s.radio.busy_backoffs), s.radio.last_rssi);
    ui::body_line(3, radio, ui::kMuted);
    ui::body_line(4, "Station", ui::kText);
    ui::body_line(5, "  dest   " + (station.size() >= 16 ? station.substr(0, 16) + "..." : "(not set)"));
    ui::body_line(6, std::string("  path   ") + (s.station_known ? "known" : "not yet"),
                  s.station_known ? ui::kOk : ui::kWarn);
    if (_pinging) {
      ui::body_line(8, "  PING   waiting for Station...", ui::kLive);
    } else if (!_pinged) {
      ui::body_line(8, "  PING   press to test");
    } else if (_ping_result == net::Result::Ok) {
      ui::body_line(8, "  PING   ok, " + std::to_string(_ping_ms) + " ms round trip", ui::kOk);
    } else {
      ui::body_line(8, std::string("  PING   failed: ") + net::describe(_ping_result), ui::kWarn);
    }
    auto lines = ui::wrap("Boot " + (s.boot.empty() ? std::string("still starting") : s.boot));
    ui::body_line(9, lines.size() > 0 ? lines[0] : "", ui::kMuted);
    ui::body_line(10, lines.size() > 1 ? lines[1] : "", ui::kMuted);
    ui::footer("press: PING   roll left: back");
  }

  bool _pinging = false;
  bool _pinged = false;
  net::Result _ping_result = net::Result::Ok;
  uint32_t _ping_ms = 0;
  uint32_t _drawn_at = 0;
};

}  // namespace

App& apps::signal_app() {
  static SignalApp app;
  return app;
}
