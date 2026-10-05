// Beacon — emergency alerts.
//
// Station pushes BEACON/BEACON_ALERT to every paired Scout the moment a
// Beacon is raised or cleared; the Scout shows a full-screen alert over
// whatever is on screen (the lock screen too) until acknowledged. Catch-up
// also checks BEACON_GET, so an alert sent while the Scout was off or out of
// range still shows. The Beacon app lists current + recent alerts and can
// raise one (behind a confirmation; Station applies its own cooldown).
#include <algorithm>
#include <cctype>
#include <string>
#include <vector>

#include <Arduino.h>
#include <microReticulum.h>

#include "app.h"
#include "prompt.h"
#include "tasks.h"
#include "store.h"
#include "ui.h"

namespace {

using waylink::Field;

struct BeaconInfo {
  std::string id, title, severity, body, author;
  uint64_t ts = 0;
  bool active = false;
};

BeaconInfo from_value(const waylink::Value& v) {
  BeaconInfo b;
  b.id = v.text("id");
  b.title = v.text("t");
  b.severity = v.text("sev", "emergency");
  b.body = v.text("b");
  b.author = v.text("a");
  b.ts = v.uint("ts");
  b.active = v.flag("on");
  return b;
}

uint16_t severity_bg(const std::string& sev) {
  if (sev == "emergency") return ui::kError;
  if (sev == "urgent") return ui::kWarn;
  return ui::kSelect;  // advisory
}

std::string upper(std::string s) {
  for (auto& c : s) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
  return s;
}

// Alerts saved on the Scout, newest first: shown when Station is out of
// reach, and an acknowledged one isn't raised again after a reboot.
//   /wp_beacons   id \t sev \t ts \t active \t acked \t author \t title \t body
const char* const kSavedPath = "/wp_beacons";
const size_t kMaxSaved = 12;

struct Saved {
  BeaconInfo b;
  bool acked;
};
std::vector<Saved> g_saved;
bool g_saved_dirty = false;

Saved* saved(const std::string& id) {
  for (auto& s : g_saved)
    if (s.b.id == id) return &s;
  return nullptr;
}

// Latest word on a Beacon (from a push, BEACON_GET or BEACON_LIST).
void remember(const BeaconInfo& b) {
  if (b.id.empty()) return;
  Saved* s = saved(b.id);
  if (s) {
    if (s->b.active != b.active || s->b.title != b.title) g_saved_dirty = true;
    s->b = b;
    return;
  }
  g_saved.insert(g_saved.begin(), {b, false});
  if (g_saved.size() > kMaxSaved) g_saved.pop_back();
  std::stable_sort(g_saved.begin(), g_saved.end(),
                   [](const Saved& x, const Saved& y) { return x.b.ts > y.b.ts; });
  g_saved_dirty = true;
}

bool acknowledged(const std::string& id) {
  const Saved* s = saved(id);
  return s && s->acked;
}

void acknowledge(const BeaconInfo& b) {
  remember(b);
  Saved* s = saved(b.id);
  if (s && !s->acked) {
    s->acked = true;
    g_saved_dirty = true;
  }
}

// -- the full-screen alert ------------------------------------------------------

class AlertApp : public App {
 public:
  const char* title() const override { return "BEACON"; }

  void show(const BeaconInfo& b) {
    if (apps::current() != this) _return_to = apps::current();
    _beacon = b;
    apps::open(*this);
  }
  bool showing(const std::string& id) const { return apps::current() == this && _beacon.id == id; }
  bool showing() const { return apps::current() == this; }

  void cleared(const std::string& id) {
    if (!showing(id)) return;
    _beacon.active = false;
    draw();
  }

  void enter() override {
    _blink = false;
    _last_blink = millis();
    draw();
  }

  void on_event(const input::Event& e) override {
    if (e.kind != input::Kind::Select && e.kind != input::Kind::Enter) return;
    acknowledge(_beacon);
    App* back = _return_to ? _return_to : &apps::home_app();
    _return_to = nullptr;
    apps::open(*back);
  }

  void tick() override {
    if (!_beacon.active) return;  // a cleared Beacon doesn't flash
    if (millis() - _last_blink < 500) return;
    _last_blink = millis();
    _blink = !_blink;
    auto& t = ui::tft();
    uint16_t c = _blink ? ui::kText : severity_bg(_beacon.severity);
    for (int i = 0; i < 4; i++) t.drawRect(i, i, ui::kWidth - 2 * i, ui::kHeight - 2 * i, c);
    ui::mark_dirty(0, 0, ui::kWidth, 4);
    ui::mark_dirty(0, ui::kHeight - 4, ui::kWidth, 4);
    ui::mark_dirty(0, 0, 4, ui::kHeight);
    ui::mark_dirty(ui::kWidth - 4, 0, 4, ui::kHeight);
  }

 private:
  void draw() {
    auto& t = ui::tft();
    uint16_t bg = _beacon.active ? severity_bg(_beacon.severity) : ui::kBg;
    t.fillRect(0, 0, ui::kWidth, ui::kHeight, bg);  // not fillScreen (see ui::init)
    t.setTextDatum(TC_DATUM);
    t.setTextColor(ui::kText, bg);
    std::string head = _beacon.active ? upper(_beacon.severity) : "CLEARED";
    t.drawString(head.c_str(), ui::kWidth / 2, 12, 4);
    t.setTextDatum(TL_DATUM);
    int y = 46;
    // ui::wrap measures in the body font; font 4 is roughly twice as wide.
    for (auto& line : ui::wrap(_beacon.title, (ui::kWidth - 24) / 2)) {
      if (y > 100) break;
      t.drawString(line.c_str(), 12, y, 4);
      y += 26;
    }
    y += 4;
    for (auto& line : ui::wrap(_beacon.body, ui::kWidth - 24)) {
      if (y > ui::kHeight - 40) break;
      t.drawString(line.c_str(), 12, y, 2);
      y += 18;
    }
    t.setTextDatum(BC_DATUM);
    std::string foot = _beacon.active ? "Press to acknowledge" : "This Beacon was cleared - press to close";
    if (!_beacon.author.empty() && _beacon.active) foot = "from " + _beacon.author + "   " + foot;
    t.drawString(ui::to_display(foot).c_str(), ui::kWidth / 2, ui::kHeight - 10, 2);
    t.setTextDatum(TL_DATUM);
    ui::mark_dirty();
    ui::mirror_row(0, head + ": " + _beacon.title, false);
    ui::mirror_row(1, _beacon.body, false);
  }

  BeaconInfo _beacon;
  App* _return_to = nullptr;
  bool _blink = false;
  uint32_t _last_blink = 0;
};

AlertApp& alert() {
  static AlertApp app;
  return app;
}

// -- the Beacon app ---------------------------------------------------------------

class BeaconApp : public App {
 public:
  const char* title() const override { return "Beacon"; }

  void enter() override { show_list(); }

  void on_event(const input::Event& e) override {
    using input::Kind;
    if (_mode == Mode::List) {
      int n = static_cast<int>(_rows.size());
      if (e.kind == Kind::Left || e.kind == Kind::Backspace) {
        apps::home();
        return;
      }
      if (e.kind == Kind::Up && _sel > 0) _sel--;
      else if (e.kind == Kind::Down && _sel + 1 < n) _sel++;
      else if (e.kind == Kind::Select || e.kind == Kind::Enter || e.kind == Kind::Right) {
        if (_sel == 0) start_raise();
        else if (_sel == 1 && _current.active) alert().show(_current);
        return;
      } else return;
      draw_list();
      return;
    }
    Prompt::Result r = _prompt.on_event(e);
    if (r == Prompt::Result::Back) {
      show_list();
      return;
    }
    if (r == Prompt::Result::Submitted) raise_step(_prompt.value());
  }

 private:
  enum class Mode { List, Severity, Title, Body, Confirm };

  void show_list() {
    _mode = Mode::List;
    ui::title_bar(title());
    ui::clear_body();
    _note = "Loading...";
    draw_list();
    // Current Beacon, then the recent ones; saved alerts if Station is away.
    // A newer show_list() supersedes this one (gen).
    uint32_t gen = ++_list_gen;
    rpc::ask("BEACON", "BEACON_GET", {Field::boolean("compact", true)},
              [this, gen](net::Result r, waylink::Reply& reply) {
                if (gen != _list_gen) return;
                _current = BeaconInfo();
                _history.clear();
                if (r != net::Result::Ok) {
                  _note = std::string("Station: ") + net::describe(r) + " - saved alerts";
                  for (const auto& sv : g_saved) {
                    _history.push_back(sv.b);
                    if (sv.b.active && _current.id.empty()) _current = sv.b;
                  }
                  if (showing_list()) draw_list();
                  return;
                }
                const waylink::Value* b = reply.payload().get("beacon");
                if (b && b->type == waylink::Value::Map) {
                  _current = from_value(*b);
                  remember(_current);
                }
                rpc::ask("BEACON", "BEACON_LIST", {Field::boolean("compact", true)},
                          [this, gen](net::Result r, waylink::Reply& reply) {
                            if (gen != _list_gen) return;
                            _note.clear();
                            if (r == net::Result::Ok) {
                              const waylink::Value* list = reply.payload().get("beacons");
                              if (list && list->type == waylink::Value::Array)
                                for (const auto& v : list->items) {
                                  _history.push_back(from_value(v));
                                  remember(_history.back());
                                }
                            }
                            if (showing_list()) draw_list();
                          });
              });
  }

  bool showing_list() const { return apps::current() == this && _mode == Mode::List; }

  void draw_list() {
    _rows.clear();
    _rows.push_back("! Raise a Beacon");
    _rows.push_back(_current.active ? "ACTIVE: " + _current.title : "No active Beacon");
    for (const auto& b : _history) {
      if (b.id == _current.id && _current.active) continue;
      _rows.push_back("  " + b.severity + ": " + b.title + (b.active ? "" : " (cleared)"));
    }
    if (_sel >= static_cast<int>(_rows.size())) _sel = 0;
    ui::list(_rows, _sel, _top);
    ui::footer(_note.empty() ? "press: open   roll left: home" : _note,
               _note.empty() ? ui::kMuted : _note == "Loading..." ? ui::kLive : ui::kWarn);
  }

  // Raise: severity -> title -> details -> type SEND.
  void start_raise() {
    _mode = Mode::Severity;
    Prompt::Options o;
    o.max_len = 1;
    o.digits_only = true;
    _prompt.open("Raise a Beacon",
                 "This alerts everyone in camp. How serious? 1 = emergency, 2 = urgent, 3 = advisory.",
                 o);
  }

  void raise_step(const std::string& v) {
    Prompt::Options o;
    switch (_mode) {
      case Mode::Severity:
        if (v != "1" && v != "2" && v != "3") {
          _prompt.set_error("Type 1, 2, or 3.");
          return;
        }
        _new_sev = v == "1" ? "emergency" : v == "2" ? "urgent" : "advisory";
        _mode = Mode::Title;
        o.max_len = 60;
        _prompt.open("Raise a Beacon", "Headline (what's happening):", o);
        return;
      case Mode::Title:
        if (v.empty()) return;
        _new_title = v;
        _mode = Mode::Body;
        o.max_len = 120;
        _prompt.open("Raise a Beacon", "Details (where, what to do):", o);
        return;
      case Mode::Body:
        if (v.empty()) return;
        _new_body = v;
        _mode = Mode::Confirm;
        o.max_len = 4;
        _prompt.open("Raise a Beacon",
                     upper(_new_sev) + ": " + _new_title + ". Type SEND to alert the whole camp.", o);
        return;
      case Mode::Confirm: {
        if (upper(v) != "SEND") {
          _prompt.set_error("Type SEND to confirm, or roll left to cancel.");
          return;
        }
        if (_sending) return;
        _sending = true;
        _prompt.set_note("Sending...");
        rpc::ask("BEACON", "BEACON_PUSH",
                  {Field::text("title", _new_title), Field::text("body", _new_body),
                   Field::text("severity", _new_sev)},
                  [this](net::Result r, waylink::Reply& reply) {
                    _sending = false;
                    if (apps::current() != this || _mode != Mode::Confirm) return;
                    if (r != net::Result::Ok) {
                      _prompt.set_error(std::string("Not sent: ") +
                                        (r == net::Result::Error ? reply.error : net::describe(r)));
                      return;
                    }
                    show_list();
                  },
                  1, 15000);
        return;
      }
      case Mode::List:
        return;
    }
  }

  Mode _mode = Mode::List;
  bool _sending = false;
  uint32_t _list_gen = 0;
  BeaconInfo _current;
  std::vector<BeaconInfo> _history;
  std::vector<std::string> _rows;
  int _sel = 0, _top = 0;
  std::string _note;
  Prompt _prompt;
  std::string _new_sev, _new_title, _new_body;
};

}  // namespace

App& apps::beacon_app() {
  static BeaconApp app;
  return app;
}

void apps::beacon_event(const waylink::Value& compact) {
  BeaconInfo b = from_value(compact);
  if (b.id.empty()) return;
  remember(b);
  if (!b.active) {
    alert().cleared(b.id);
    return;
  }
  if (acknowledged(b.id) || alert().showing(b.id)) return;
  Serial.printf("beacon: %s %s\n", b.severity.c_str(), b.title.c_str());
  alert().show(b);
}

bool apps::beacon_showing() { return alert().showing(); }

void apps::check_beacon() {
  rpc::ask("BEACON", "BEACON_GET", {Field::boolean("compact", true)},
            [](net::Result r, waylink::Reply& reply) {
              if (r != net::Result::Ok) return;
              const waylink::Value* b = reply.payload().get("beacon");
              if (b && b->type == waylink::Value::Map) apps::beacon_event(*b);
            });
}

void apps::beacon_load() {
  g_saved.clear();
  auto lines = store::read_lines(kSavedPath);
  for (const auto& line : lines) {
    auto f = store::split_tabs(line);
    if (f.size() < 8) continue;
    BeaconInfo b;
    b.id = f[0];
    b.severity = f[1];
    b.ts = strtoull(f[2].c_str(), nullptr, 10);
    b.active = f[3] == "1";
    b.author = store::unescape(f[5]);
    b.title = store::unescape(f[6]);
    b.body = store::unescape(f[7]);
    g_saved.push_back({b, f[4] == "1"});
  }
}

void apps::beacon_save() {
  if (!g_saved_dirty) return;
  g_saved_dirty = false;
  std::string out;
  for (const auto& s : g_saved) {
    const BeaconInfo& b = s.b;
    out += b.id + "\t" + b.severity + "\t" + std::to_string(b.ts) + "\t" + (b.active ? "1" : "0") +
           "\t" + (s.acked ? "1" : "0") + "\t" + store::escape(b.author) + "\t" +
           store::escape(b.title) + "\t" + store::escape(b.body) + "\n";
  }
  RNS::Utilities::OS::write_file(kSavedPath, RNS::Bytes(out));
}
