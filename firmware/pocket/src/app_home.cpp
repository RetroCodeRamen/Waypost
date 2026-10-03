// Home launcher — Cybiko-style tile grid.
#include <string>

#include "app.h"
#include "station_link.h"
#include "ui.h"

namespace {

struct Tile {
  const char* name;
  const char* hint;
  App& (*app)();
};

const Tile kTiles[] = {
    {"Dispatch", "Messages", apps::dispatch_app},
    {"Fieldbook", "Camp wiki", apps::fieldbook_app},
    {"Trailhead", "Station pages", apps::trailhead_app},
    {"Signal", "Radio + Station", apps::signal_app},
};
constexpr int kCols = 2;
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
    bool known = station_link::station_known();
    if (known != _known) {
      _known = known;
      draw_footer();
    }
  }

 private:
  void draw_tile(int i) {
    const int pad = 8;
    const int w = (ui::kWidth - pad * 3) / kCols;
    const int h = (ui::kBodyBottom - ui::kBodyTop - pad * 3) / 2;
    int x = pad + (i % kCols) * (w + pad);
    int y = ui::kBodyTop + pad + (i / kCols) * (h + pad);
    bool sel = i == _sel;
    auto& t = ui::tft();
    uint16_t bg = sel ? TFT_DARKCYAN : TFT_BLACK;
    t.fillRoundRect(x, y, w, h, 8, bg);
    t.drawRoundRect(x, y, w, h, 8, sel ? TFT_WHITE : TFT_DARKGREY);
    t.setTextDatum(MC_DATUM);
    t.setTextColor(TFT_WHITE, bg);
    t.drawString(kTiles[i].name, x + w / 2, y + h / 2 - 10, 4);
    t.setTextColor(sel ? TFT_WHITE : TFT_LIGHTGREY, bg);
    t.drawString(kTiles[i].hint, x + w / 2, y + h / 2 + 16, 2);
    t.setTextDatum(TL_DATUM);
    ui::mirror_row(i, std::string(kTiles[i].name) + " - " + kTiles[i].hint, sel);
  }

  void draw_tiles() {
    for (int i = 0; i < kCount; i++) draw_tile(i);
  }

  void draw_footer() {
    _known = station_link::station_known();
    ui::footer(station_link::node_id() + (_known ? "   Station reachable" : "   looking for Station..."),
               _known ? TFT_GREEN : TFT_DARKGREY);
  }

  int _sel = 0;
  bool _known = false;
};

}  // namespace

App& apps::home_app() {
  static HomeApp app;
  return app;
}
