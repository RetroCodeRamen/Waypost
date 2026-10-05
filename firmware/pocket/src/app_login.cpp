// Login — username + password (2026-10-05, docs/identity.md).
//
// The Scout works out the person's identity key from username + password
// (kdf.*, ~4 s), then proves it to Station by signing a one-time challenge
// (PROFILE/LOGIN_NONCE, LOGIN), which binds this Scout to the account. The
// password never crosses the radio. With Station out of reach the person can
// still sign in — the key needs nothing but the password — and the Scout
// finishes the login with Station when it's next in reach.
#include <string>

#include <Arduino.h>
#include <microReticulum.h>
#include <microReticulum/Cryptography/Ed25519.h>

#include "account.h"
#include "app.h"
#include "certs.h"
#include "kdf.h"
#include "prompt.h"
#include "station_link.h"
#include "ui.h"

namespace {

using waylink::Field;

// One definite answer per boot; after a timeout, try again at most once a
// minute (never every loop pass — that would flood the channel).
bool g_identity_settled = false;
uint32_t g_identity_last_try = 0;
bool g_identity_tried = false;

std::string raw(const RNS::Bytes& b) { return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
RNS::Bytes bytes(const std::string& s) { return RNS::Bytes(reinterpret_cast<const uint8_t*>(s.data()), s.size()); }

std::string my_dest() {
  RNS::Bytes d;
  d.assignHex(station_link::dest_hex().c_str());
  return raw(d);
}

// Station's half of a login: challenge, signed answer. Ok, or Error with
// out_error set (wrong_password, no_identity_yet, unknown_user...).
station_link::Result station_login(const std::string& username, const std::string& seed,
                                   std::string& display_name, std::string& out_error) {
  waylink::Reply reply;
  auto r = station_link::request("PROFILE", "LOGIN_NONCE",
                                 {Field::text("transport_dest", station_link::dest_hex())}, reply, 2, 8000);
  if (r != station_link::Result::Ok) {
    out_error = reply.error;
    return r;
  }
  std::string nonce = reply.payload().bytes("nonce");
  // server/services/auth/pairing.py PairingService.login_bytes
  std::string msg = "WAYPOST-LOGIN-1\n" + station_link::node_id() + "\n" + my_dest() + "\n" + nonce;
  RNS::Cryptography::Ed25519PrivateKey key(bytes(seed));
  std::string sig = raw(key.sign(bytes(msg)));
  r = station_link::request("PROFILE", "LOGIN",
                            {Field::text("u", username), Field::bytes("rd", my_dest()),
                             Field::bytes("sig", sig), Field::text("transport_dest", station_link::dest_hex())},
                            reply, 1, 10000);
  if (r != station_link::Result::Ok) {
    out_error = reply.error;
    return r;
  }
  display_name = reply.payload().text("display_name", username);
  return r;
}

std::string explain(const std::string& error) {
  if (error == "wrong_password") return "That password doesn't match this account.";
  if (error == "unknown_user") return "Station has no account with that name.";
  if (error == "no_identity_yet")
    return "Sign in once on the Station portal first (that sets up your identity), then try again.";
  if (error == "account pending admin approval") return "This account is waiting for an admin to approve it.";
  return "Station says: " + error;
}

class LoginApp : public App {
 public:
  const char* title() const override { return "Sign in"; }

  void enter() override { ask_user(); }

  void on_event(const input::Event& e) override {
    Prompt::Result r = _prompt.on_event(e);
    if (r == Prompt::Result::Back && _mode == Mode::Password) {
      ask_user();
      return;
    }
    if (r != Prompt::Result::Submitted) return;
    if (_mode == Mode::User) {
      if (_prompt.value().empty()) return;
      _user = _prompt.value();
      ask_password();
    } else if (_mode == Mode::Password) {
      sign_in(_prompt.value());
    } else if (_mode == Mode::Offline) {
      std::string v = _prompt.value();
      for (auto& c : v) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
      if (v != "YES") {
        ask_password();
        return;
      }
      finish(_user, _user, true);
    }
  }

  void set_note(const std::string& note) { _note = note; }

 private:
  enum class Mode { User, Password, Offline };

  void ask_user() {
    _mode = Mode::User;
    Prompt::Options o;
    o.max_len = 32;
    o.allow_back = false;  // nothing useful works until signed in
    _prompt.open(title(), "Your Waypost username:", o);
    if (!_note.empty()) _prompt.set_note(_note);
  }

  void ask_password() {
    _mode = Mode::Password;
    Prompt::Options o;
    o.masked = true;
    o.max_len = 64;
    _prompt.open(title(), "Password for " + _user + ":", o);
  }

  void sign_in(const std::string& password) {
    _prompt.set_note("Working out your key (about 5 seconds)...");
    _prompt.draw();
    ui::present();
    uint32_t t0 = millis();
    _seed = kdf::identity_seed(_user, password);
    _prompt.clear();
    Serial.printf("login: key in %lu ms\n", static_cast<unsigned long>(millis() - t0));
    if (_seed.size() != 32) {
      _prompt.set_error("Not enough memory to work out the key - restart and try again.");
      return;
    }
    if (!station_link::station_known()) {
      // Signing in offline: the key is real if the password is; Station
      // checks it when it's next in reach.
      _mode = Mode::Offline;
      Prompt::Options o;
      o.max_len = 3;
      _prompt.open(title(),
                   "Station isn't in reach, so the password can't be checked yet. "
                   "Sign in anyway? Type YES (your messages wait until it's checked).",
                   o);
      return;
    }
    _prompt.set_note("Checking with Station...");
    std::string name, error;
    auto r = station_login(_user, _seed, name, error);
    if (r == station_link::Result::Error) {
      _prompt.set_error(explain(error));
      return;
    }
    if (r != station_link::Result::Ok) {
      _prompt.set_error(std::string("Couldn't reach Station (") + station_link::describe(r) + "). Try again.");
      return;
    }
    finish(_user, name, false);
  }

  void finish(const std::string& user, const std::string& name, bool offline) {
    account::set_user(user, name);  // a different person: clears the old one's data
    account::clear_unpair_pending();
    certs::set_identity(_seed, "");  // no PIN yet: Settings offers one
    std::fill(_seed.begin(), _seed.end(), '\0');
    _seed.clear();
    _note.clear();
    g_identity_settled = g_identity_tried = false;  // WHOAMI next (confirms, or finishes an offline login)
    Serial.printf("login: %s signed in%s\n", user.c_str(), offline ? " (offline, not yet checked)" : "");
    apps::home();
  }

  Mode _mode = Mode::User;
  Prompt _prompt;
  std::string _note, _user, _seed;
};

LoginApp& instance() {
  static LoginApp app;
  return app;
}

void signed_out(const std::string& why) {
  account::unpair();
  instance().set_note(why);
  apps::open(instance());
}

}  // namespace

App& apps::login_app() { return instance(); }

void apps::check_identity() {
  if (g_identity_settled && !account::unpair_pending()) return;
  if (!station_link::station_known()) {
    station_link::seek_station();
    return;
  }
  if (g_identity_tried && millis() - g_identity_last_try < 60000) return;
  g_identity_tried = true;
  g_identity_last_try = millis();

  waylink::Reply reply;
  if (account::unpair_pending()) {
    // Finish a sign-out done on this Scout before asking who we are —
    // otherwise WHOAMI would hand the old account straight back.
    if (station_link::request("PROFILE", "UNPAIR", {Field::text("transport_dest", station_link::dest_hex())}, reply, 2, 8000) != station_link::Result::Ok) {
      return;  // try again in a minute
    }
    account::clear_unpair_pending();
    Serial.println("identity: Station unpaired this Scout");
  }

  auto r = station_link::request("PROFILE", "WHOAMI", {Field::text("transport_dest", station_link::dest_hex())}, reply, 2, 8000);
  if (r == station_link::Result::Ok) {
    g_identity_settled = true;
    std::string user = reply.payload().text("username");
    std::string name = reply.payload().text("display_name", user);
    if (account::paired() && user != account::username()) {
      // Bound to someone else on Station (re-paired from the portal).
      signed_out("This Scout now belongs to " + user + " on Station. Sign in to continue.");
      return;
    }
    if (account::paired() && name != account::display_name()) account::set_user(user, name);
    Serial.printf("identity: %s (confirmed)\n", user.c_str());
  } else if (r == station_link::Result::Error && reply.error == "not_paired" && account::paired()) {
    // Signed in while Station was away (or unpaired from the portal): log
    // in now if the key is open; otherwise wait for the next unlock.
    if (!certs::key_unlocked()) return;
    // The key is already worked out; sign Station's challenge with it.
    std::string name, error;
    auto lr = station_link::Result::Error;
    {
      // certs keeps the seed private; sign through it.
      waylink::Reply nonce_reply;
      auto nr = station_link::request("PROFILE", "LOGIN_NONCE",
                                      {Field::text("transport_dest", station_link::dest_hex())}, nonce_reply, 2, 8000);
      if (nr != station_link::Result::Ok) return;
      std::string nonce = nonce_reply.payload().bytes("nonce");
      std::string msg = "WAYPOST-LOGIN-1\n" + station_link::node_id() + "\n" + my_dest() + "\n" + nonce;
      std::string sig = certs::sign(msg);
      waylink::Reply login_reply;
      lr = station_link::request("PROFILE", "LOGIN",
                                 {Field::text("u", account::username()), Field::bytes("rd", my_dest()),
                                  Field::bytes("sig", sig), Field::text("transport_dest", station_link::dest_hex())},
                                 login_reply, 1, 10000);
      error = login_reply.error;
      name = login_reply.payload().text("display_name", account::username());
    }
    if (lr == station_link::Result::Ok) {
      g_identity_settled = true;
      account::set_user(account::username(), name);
      Serial.println("identity: login finished with Station");
    } else if (lr == station_link::Result::Error) {
      g_identity_settled = true;
      signed_out(explain(error) + " Sign in again.");
    }
  } else if (r == station_link::Result::Error) {
    g_identity_settled = true;
  }
  // Timeouts: keep the cached account and try again later.
}
