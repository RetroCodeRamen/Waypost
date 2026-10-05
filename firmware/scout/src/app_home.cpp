// Home launcher — Cybiko-style tile grid.
#include <string>

#include "account.h"
#include "app.h"
#include "net.h"
#include "ui.h"

namespace {

struct Tile {
  const char* name;
  const char* hint;
  App& (*app)();
};

const Tile kTiles[] = {
    {"Dispatch", "Messages", apps::dispatch_app},
    {"Beacon", "Emergency alerts", apps::beacon_app},
    {"Fieldbook", "Camp wiki", apps::fieldbook_app},
    {"Trailhead", "Station pages", apps::trailhead_app},
    {"Signal", "Radio + Station", apps::signal_app},
    {"Settings", "PIN, pairing", apps::settings_app},
};
constexpr int kCols = 3;
constexpr int kRows = 3;
constexpr int kCount = sizeof(kTiles) / sizeof(kTiles[0]);

class HomeApp : public App {
 public:
  const char* title() const override { return "Waypost Scout"; }

  void enter() override {
    ui::title_bar(title());
    ui::clear_body();
    draw_tiles();
    draw_footer();
  }

  void on_event(const input::Event& e) override {
    using input::Kind;
    int prev = _sel;
    switch (e.kind) {
      case Kind::Left: if (_sel % kCols > 0) _sel--; break;
      case Kind::Right: if (_sel % kCols < kCols - 1 && _sel + 1 < kCount) _sel++; break;
      case Kind::Up: if (_sel >= kCols) _sel -= kCols; break;
      case Kind::Down: if (_sel + kCols < kCount) _sel += kCols; break;
      case Kind::Select:
      case Kind::Enter:
        apps::open(kTiles[_sel].app());
        return;
      case Kind::Char:
        // Shortcut: first letter of an app name.
        for (int i = 0; i < kCount; i++) {
          if (tolower(e.ch) == tolower(kTiles[i].name[0])) {
            apps::open(kTiles[i].app());
            return;
          }
        }
        return;
      default:
        return;
    }
    if (_sel != prev) {
      draw_tile(prev);
      draw_tile(_sel);
    }
  }

  void tick() override {
    // Footer reflects Station reachability as paths are learned.
    static uint32_t last = 0;
    if (millis() - last < 1000) return;
    last = millis();
    net::Status st = net::status();
    bool known = st.station_known;
    int radio = st.ready ? 1 : st.failed ? 2 : 0;
    if (known != _known || radio != _radio || account::display_name() != _who) {
      _radio = radio;
      _who = account::display_name();
      draw_footer();
    }
  }

 private:
  void draw_tile(int i) {
    const int pad = 6;
    const int w = (ui::kWidth - pad * (kCols + 1)) / kCols;
    const int h = (ui::kBodyBottom - ui::kBodyTop - pad * (kRows + 1)) / kRows;
    int x = pad + (i % kCols) * (w + pad);
    int y = ui::kBodyTop + pad + (i / kCols) * (h + pad);
    bool sel = i == _sel;
    auto& t = ui::tft();
    uint16_t bg = sel ? ui::kSelect : ui::kBg;
    t.fillRoundRect(x, y, w, h, 6, bg);
    t.drawRoundRect(x, y, w, h, 6, sel ? ui::kLive : ui::kBorder);
    t.setTextDatum(MC_DATUM);
    t.setTextColor(ui::kText, bg);
    t.setFont(&fonts::Font2);
    t.drawString(kTiles[i].name, x + w / 2, y + h / 2 - 7);
    t.setTextColor(sel ? ui::kText : ui::kMuted, bg);
    t.setFont(&fonts::Font0);
    t.drawString(kTiles[i].hint, x + w / 2, y + h / 2 + 11);
    t.setTextDatum(TL_DATUM);
    ui::mark_dirty(x, y, w, h);
    ui::mirror_row(i, std::string(kTiles[i].name) + " - " + kTiles[i].hint, sel);
  }

  void draw_tiles() {
    for (int i = 0; i < kCount; i++) draw_tile(i);
  }

  void draw_footer() {
    net::Status st = net::status();
    _known = st.station_known;
    std::string who = account::paired() ? account::display_name() : std::string("not paired");
    if (st.failed) {
      ui::footer(who + "   radio failed to start - restart the Scout", ui::kError);
    } else if (!st.ready) {
      ui::footer(who + "   radio starting...", ui::kMuted);
    } else {
      ui::footer(who + (_known ? "   Station reachable" : "   looking for Station..."),
                 _known ? ui::kLive : ui::kMuted);
    }
  }

  int _sel = 0;
  bool _known = false;
  int _radio = -1;  // 0 starting, 1 ready, 2 failed
  std::string _who;
};

}  // namespace

App& apps::home_app() {
  static HomeApp app;
  return app;
}
