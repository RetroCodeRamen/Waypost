// Signal — this Scout's radio identity and its link to Station, with a PING.
#include <string>

#include <Arduino.h>

#include "app.h"
#include "station_link.h"
#include "ui.h"

#include <microReticulum.h>

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
    } else if (e.kind == Kind::Select || e.kind == Kind::Enter) {
      ping();
    }
  }

  void tick() override {
    static uint32_t last = 0;
    if (millis() - last < 1000) return;
    last = millis();
    bool known = station_link::station_known();
    if (known != _known) draw();
  }

 private:
  void ping() {
    ui::footer("PING...", ui::kLive);
    waylink::Reply reply;
    uint32_t start = millis();
    _ping_result = station_link::request("CORE", "PING", {}, reply, 1, 15000);
    _ping_ms = millis() - start;
    _pinged = true;
    draw();
  }

  void draw() {
    _known = station_link::station_known();
    std::string station = WAYPOST_STATION_DEST_HASH;
    ui::body_line(0, "This Scout", ui::kText);
    ui::body_line(1, "  node   " + station_link::node_id());
    ui::body_line(2, "  dest   " + station_link::dest_hex().substr(0, 16) + "...");
    ui::body_line(4, "Station", ui::kText);
    ui::body_line(5, "  dest   " + (station.size() >= 16 ? station.substr(0, 16) + "..." : "(not set)"));
    ui::body_line(6, std::string("  path   ") + (_known ? "known" : "not yet"),
                  _known ? ui::kOk : ui::kWarn);
    if (!_pinged) {
      ui::body_line(8, "  PING   press to test");
    } else if (_ping_result == station_link::Result::Ok) {
      ui::body_line(8, "  PING   ok, " + std::to_string(_ping_ms) + " ms round trip", ui::kOk);
    } else {
      ui::body_line(8, std::string("  PING   failed: ") + station_link::describe(_ping_result),
                    ui::kWarn);
    }
    RNS::Bytes last;
    if (RNS::Utilities::OS::read_file("/waypost_lastboot", last) > 0) {
      std::string s(reinterpret_cast<const char*>(last.data()), last.size());
      auto lines = ui::wrap("Last boot " + s.substr(0, s.find('\n')));
      ui::body_line(9, lines.size() > 0 ? lines[0] : "", ui::kMuted);
      ui::body_line(10, lines.size() > 1 ? lines[1] : "", ui::kMuted);
    }
    ui::footer("press: PING   roll left: back");
  }

  bool _known = false;
  bool _pinged = false;
  station_link::Result _ping_result = station_link::Result::Ok;
  uint32_t _ping_ms = 0;
};

}  // namespace

App& apps::signal_app() {
  static SignalApp app;
  return app;
}
