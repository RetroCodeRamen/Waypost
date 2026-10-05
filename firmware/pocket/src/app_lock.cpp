// Lock screen — shown at boot and after idle when a PIN is set.
//
// There is no bypass: the only way past a forgotten PIN is RESET, which
// unpairs this Scout (account + PIN wiped; it has to be paired again with a
// code from the portal, which needs the account owner). The PIN guards the
// UI only — flash isn't encrypted (docs/security.md).
#include <cctype>
#include <string>

#include <Arduino.h>

#include "account.h"
#include "certs.h"
#include "app.h"
#include "prompt.h"
#include "ui.h"

namespace {

constexpr int kTriesBeforeBackoff = 5;
constexpr uint32_t kFirstBackoffMs = 30000;

class LockApp : public App {
 public:
  const char* title() const override { return "Locked"; }

  void lock(App* return_to) {
    _return_to = return_to;
    apps::open(*this);
  }
  bool active() const { return apps::current() == this; }

  void enter() override {
    Prompt::Options opts;
    opts.masked = true;
    opts.max_len = 8;
    opts.allow_back = false;
    _prompt.open(title(), "Enter your PIN, then press Enter.", opts);
    note_default();
  }

  void on_event(const input::Event& e) override {
    if (in_backoff()) return;
    if (_prompt.on_event(e) != Prompt::Result::Submitted) return;
    std::string v = _prompt.value();
    _prompt.clear();

    std::string upper = v;
    for (auto& c : upper) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
    if (upper == "RESET") {
      account::unpair();
      _fails = 0;
      apps::open(apps::login_app());
      return;
    }
    if (account::check_pin(v)) {
      _fails = 0;
      _backoff_ms = kFirstBackoffMs;
      App* back = _return_to ? _return_to : &apps::home_app();
      _return_to = nullptr;
      apps::open(*back);
      return;
    }
    _fails++;
    if (_fails % kTriesBeforeBackoff == 0) {
      _backoff_until = millis() + _backoff_ms;
      _backoff_ms *= 2;
      tick();
    } else {
      _prompt.set_error("Wrong PIN.");
    }
  }

  void tick() override {
    if (!in_backoff()) {
      if (_showing_backoff) {
        _showing_backoff = false;
        note_default();
      }
      return;
    }
    uint32_t left_s = (_backoff_until - millis() + 999) / 1000;
    if (left_s != _shown_s) {
      _shown_s = left_s;
      _showing_backoff = true;
      _prompt.set_error("Too many wrong PINs. Try again in " + std::to_string(left_s) + " s.");
    }
  }

 private:
  bool in_backoff() const { return static_cast<int32_t>(_backoff_until - millis()) > 0; }
  void note_default() {
    _prompt.set_note("Forgot it? Type RESET to unpair this Scout; it will need a new pairing code.");
  }

  Prompt _prompt;
  App* _return_to = nullptr;
  int _fails = 0;
  uint32_t _backoff_ms = kFirstBackoffMs;
  uint32_t _backoff_until = 0;
  uint32_t _shown_s = 0;
  bool _showing_backoff = false;
};

LockApp& instance() {
  static LockApp app;
  return app;
}

}  // namespace

App& apps::lock_app() { return instance(); }

void apps::lock() {
  if (!account::has_pin() || instance().active()) return;
  certs::lock();  // the signing key leaves memory while locked
  instance().lock(apps::current());
}

bool apps::locked() { return instance().active(); }
