// Settings — who this Scout belongs to, the PIN, and unpairing.
//
// Changing or removing the PIN, and unpairing, all ask for the current PIN
// first, so someone holding an unlocked Scout can't quietly strip its lock.
#include <cctype>
#include <string>
#include <vector>

#include "account.h"
#include "app.h"
#include "prompt.h"
#include "station_link.h"
#include "ui.h"

namespace {

enum class Action { None, SetPin, ChangePin, RemovePin, Unpair };

class SettingsApp : public App {
 public:
  const char* title() const override { return "Settings"; }

  void enter() override { show_menu(""); }

  void on_event(const input::Event& e) override {
    using input::Kind;
    if (_mode == Mode::Menu) {
      if (e.kind == Kind::Left || e.kind == Kind::Backspace) {
        apps::home();
        return;
      }
      int n = static_cast<int>(_actions.size());
      if (e.kind == Kind::Up && _sel > 0) _sel--;
      else if (e.kind == Kind::Down && _sel + 1 < n) _sel++;
      else if (e.kind == Kind::Select || e.kind == Kind::Enter || e.kind == Kind::Right) {
        start(_actions[_sel].second);
        return;
      } else return;
      draw_menu();
      return;
    }

    Prompt::Result r = _prompt.on_event(e);
    if (r == Prompt::Result::Back) {
      show_menu("");
      return;
    }
    if (r == Prompt::Result::Submitted) submitted(_prompt.value());
  }

 private:
  enum class Mode { Menu, CurrentPin, NewPin, ConfirmPin, ConfirmUnpair };

  void show_menu(const std::string& status) {
    _mode = Mode::Menu;
    _status = status;
    _actions.clear();
    if (account::has_pin()) {
      _actions.push_back({"Change PIN", Action::ChangePin});
      _actions.push_back({"Remove PIN", Action::RemovePin});
    } else {
      _actions.push_back({"Set a PIN", Action::SetPin});
    }
    _actions.push_back({"Unpair this Scout", Action::Unpair});
    if (_sel >= static_cast<int>(_actions.size())) _sel = 0;
    ui::title_bar(title());
    ui::clear_body();
    draw_menu();
  }

  void draw_menu() {
    std::string who = account::paired()
                          ? account::display_name() + " (" + account::username() + ")"
                          : std::string("not paired");
    ui::body_line(0, "This Scout belongs to", ui::kMuted);
    ui::body_line(1, "  " + who, ui::kText);
    ui::body_line(2, "  node " + station_link::node_id(), ui::kMuted);
    ui::body_line(3, std::string("  PIN lock: ") + (account::has_pin() ? "on" : "off"),
                  account::has_pin() ? ui::kOk : ui::kMuted);
    ui::body_line(4, "");
    for (int i = 0; i < static_cast<int>(_actions.size()); i++) {
      ui::body_line(5 + i, _actions[i].first, ui::kTextDim, i == _sel);
    }
    for (int r = 5 + static_cast<int>(_actions.size()); r < ui::kBodyLines; r++) {
      ui::body_line(r, r == ui::kBodyLines - 1 ? _status : "", ui::kOk);
    }
    ui::footer("press: choose   roll left: back");
  }

  void start(Action a) {
    _action = a;
    _new_pin.clear();
    if (a == Action::SetPin) {
      ask(Mode::NewPin, "Choose a PIN of 4 to 8 digits. You'll need it after every restart and "
                        "after 5 minutes without use.");
    } else if (account::has_pin()) {
      ask(Mode::CurrentPin, "Enter your current PIN.");
    } else {
      ask(Mode::ConfirmUnpair, "Type UNPAIR to unpair this Scout. It will need a new pairing "
                               "code from the Station portal to be used again.");
    }
  }

  void ask(Mode mode, const std::string& label) {
    _mode = mode;
    Prompt::Options opts;
    opts.masked = mode == Mode::CurrentPin || mode == Mode::NewPin || mode == Mode::ConfirmPin;
    opts.digits_only = opts.masked;
    opts.max_len = opts.masked ? 8 : 10;
    _prompt.open(title(), label, opts);
  }

  void submitted(const std::string& v) {
    switch (_mode) {
      case Mode::CurrentPin:
        if (!account::check_pin(v)) {
          _prompt.clear();
          _prompt.set_error("That's not the current PIN.");
          return;
        }
        if (_action == Action::RemovePin) {
          account::clear_pin();
          show_menu("PIN removed.");
        } else if (_action == Action::ChangePin) {
          ask(Mode::NewPin, "Choose a new PIN of 4 to 8 digits.");
        } else if (_action == Action::Unpair) {
          ask(Mode::ConfirmUnpair, "Type UNPAIR to unpair this Scout. It will need a new pairing "
                                   "code from the Station portal to be used again.");
        }
        return;
      case Mode::NewPin:
        if (!account::valid_pin_format(v)) {
          _prompt.clear();
          _prompt.set_error("Use 4 to 8 digits.");
          return;
        }
        _new_pin = v;
        ask(Mode::ConfirmPin, "Type the same PIN again.");
        return;
      case Mode::ConfirmPin:
        if (v != _new_pin) {
          _new_pin.clear();
          ask(Mode::NewPin, "Those didn't match. Choose a PIN of 4 to 8 digits.");
          return;
        }
        account::set_pin(v);
        show_menu("PIN set.");
        return;
      case Mode::ConfirmUnpair: {
        std::string upper = v;
        for (auto& c : upper) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
        if (upper != "UNPAIR") {
          _prompt.clear();
          _prompt.set_error("Type UNPAIR to confirm, or roll left to cancel.");
          return;
        }
        account::unpair();
        apps::open(apps::pairing_app());
        return;
      }
      case Mode::Menu:
        return;
    }
  }

  Mode _mode = Mode::Menu;
  Action _action = Action::None;
  std::vector<std::pair<std::string, Action>> _actions;
  int _sel = 0;
  std::string _status;
  std::string _new_pin;
  Prompt _prompt;
};

}  // namespace

App& apps::settings_app() {
  static SettingsApp app;
  return app;
}
