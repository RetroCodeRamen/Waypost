// Nearby — who's in radio range and what they can do (roadmap D6), from the
// capability records in their announces (shared/protocol/caps.py):
// Station, Outposts (and whether they reach Station), other Scouts (named
// when they're a contact; announces carry no names).
#include <string>
#include <vector>

#include <Arduino.h>

#include "app.h"
#include "contacts.h"
#include "net.h"
#include "ui.h"

namespace {

constexpr uint32_t kFreshMs = 30UL * 60UL * 1000UL;  // older than this isn't "nearby"

bool fresh(const net::Peer& p) { return p.heard_at && millis() - p.heard_at < kFreshMs; }

std::string ago(uint32_t at) {
  uint32_t s = (millis() - at) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return std::to_string(s / 60) + " min ago";
  return std::to_string(s / 3600) + " h ago";
}

bool is_station(const net::Peer& p) {
  return (p.caps.role & wp::kRoleStation) || p.dest_hex == net::station_dest().toHex();
}

std::string label(const net::Peer& p) {
  if (is_station(p)) return "Station";
  if (p.outpost()) {
    std::string name = p.caps.name;
    if (name.empty() && p.marker.find(':') != std::string::npos) name = p.marker.substr(p.marker.find(':') + 1);
    return "Outpost " + (name.empty() ? p.dest_hex.substr(0, 4) : name);
  }
  if (p.caps.role & wp::kRoleScout) {
    for (const auto& c : contacts::all())
      if (c.scout_dest == p.dest_hex) return "Scout " + c.name;
    return "Scout " + p.dest_hex.substr(0, 4);
  }
  return "Node " + p.dest_hex.substr(0, 4);
}

std::vector<std::string> services(uint32_t s) {
  static const std::pair<uint32_t, const char*> kNames[] = {
      {wp::kSvcDispatch, "Dispatch"},   {wp::kSvcPostbox, "Postbox"},     {wp::kSvcNoticeboard, "Noticeboard"},
      {wp::kSvcBeacon, "Beacon"},       {wp::kSvcFieldbook, "Fieldbook"}, {wp::kSvcCommons, "Commons"},
      {wp::kSvcLocker, "Locker"},       {wp::kSvcRollcall, "Rollcall"},   {wp::kSvcCorkboard, "Corkboard"},
      {wp::kSvcTrailhead, "Trailhead"}, {wp::kSvcSignal, "Signal"},       {wp::kSvcSync, "peer sync"},
      {wp::kSvcWifiPage, "Wi-Fi page"},
  };
  std::vector<std::string> out;
  for (const auto& n : kNames)
    if (s & n.first) out.push_back(n.second);
  return out;
}

class NearbyApp : public App {
 public:
  const char* title() const override { return "Nearby"; }

  void enter() override {
    _detail = false;
    ui::title_bar(title());
    ui::clear_body();
    draw();
  }

  void on_event(const input::Event& e) override {
    using input::Kind;
    if (_detail) {
      if (e.kind == Kind::Left || e.kind == Kind::Backspace || e.kind == Kind::Select || e.kind == Kind::Enter) {
        _detail = false;
        ui::clear_body();
        draw();
      }
      return;
    }
    int n = static_cast<int>(_peers.size());
    if (e.kind == Kind::Left || e.kind == Kind::Backspace) {
      apps::home();
      return;
    }
    if (e.kind == Kind::Up && _sel > 0) _sel--;
    else if (e.kind == Kind::Down && _sel + 1 < n) _sel++;
    else if ((e.kind == Kind::Select || e.kind == Kind::Enter || e.kind == Kind::Right) && _sel < n) {
      _detail = true;
      ui::clear_body();
      draw_detail(_peers[_sel]);
      return;
    } else {
      return;
    }
    draw();
  }

  void tick() override {
    if (!_detail && millis() - _drawn_at >= 5000) draw();  // "x min ago", new arrivals
  }

 private:
  void draw() {
    _drawn_at = millis();
    _peers.clear();
    for (const auto& p : net::status().nearby)
      if (fresh(p)) _peers.push_back(p);
    std::vector<std::string> rows;
    for (const auto& p : _peers) {
      std::string row = label(p);
      if (p.outpost() && p.caps.station == wp::kStDirect) row += "  - reaches Station";
      rows.push_back(row + "   " + ago(p.heard_at));
    }
    if (rows.empty()) rows.push_back("Nothing heard yet - devices announce every few minutes");
    if (_sel >= static_cast<int>(_peers.size())) _sel = 0;
    ui::list(rows, _sel, _top);
    ui::footer(apps::nearby_summary(), ui::kMuted);
  }

  void draw_detail(const net::Peer& p) {
    ui::body_line(0, label(p), ui::kText);
    ui::body_line(1, "  heard " + ago(p.heard_at));
    std::string reach = is_station(p)              ? "is Station"
                        : p.caps.station == wp::kStDirect ? "can reach Station"
                                                          : "no path to Station";
    ui::body_line(2, "  " + (p.has_caps ? reach : std::string("older firmware: no capability record")));
    auto svc = services(p.caps.services);
    std::string all;
    for (const auto& s : svc) all += (all.empty() ? "" : ", ") + s;
    auto lines = ui::wrap("Offers: " + (all.empty() ? std::string("-") : all));
    for (int i = 0; i < static_cast<int>(lines.size()) && i < 5; i++) ui::body_line(4 + i, "  " + lines[i]);
    ui::body_line(10, "  " + p.dest_hex, ui::kMuted);
    ui::footer("roll left: back");
  }

  std::vector<net::Peer> _peers;
  int _sel = 0, _top = 0;
  bool _detail = false;
  uint32_t _drawn_at = 0;
};

}  // namespace

App& apps::nearby_app() {
  static NearbyApp app;
  return app;
}

std::string apps::nearby_summary() {
  net::Status s = net::status();
  if (s.failed) return "radio failed to start";
  if (!s.ready) return "radio starting...";
  if (s.station_known) return "Station reachable";
  // No path of our own: an Outpost nearby that reaches Station carries for us.
  int around = 0;
  std::string via;
  for (const auto& p : s.nearby) {
    if (!fresh(p) || is_station(p)) continue;
    around++;
    if (via.empty() && p.outpost() && p.caps.station == wp::kStDirect) via = label(p);
  }
  if (!via.empty()) return "Station via " + via;
  if (around) return "no Station - " + std::to_string(around) + " nearby";
  return "looking for Station...";
}
