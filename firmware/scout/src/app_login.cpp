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
#include "tasks.h"
#include "wp_objects.h"
#include "ui.h"

namespace {

using waylink::Field;

// One definite answer per boot; after a timeout, try again at most once a
// minute (never every loop pass — that would flood the channel).
bool g_identity_settled = false;
uint32_t g_identity_last_try = 0;
bool g_identity_tried = false;
bool g_identity_busy = false;  // a check is out

std::string raw(const RNS::Bytes& b) { return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
RNS::Bytes bytes(const std::string& s) { return RNS::Bytes(reinterpret_cast<const uint8_t*>(s.data()), s.size()); }

std::string my_dest() {
  RNS::Bytes d;
  d.assignHex(net::status().dest_hex.c_str());
  return raw(d);
}

using Signer = std::function<std::string(const std::string& message)>;
using LoginDone = std::function<void(net::Result r, const std::string& display_name,
                                     const std::string& error)>;

// Station's half of a login: challenge, signed answer (the key never
// leaves the Scout). `done` gets Ok, or Error with the error code
// (wrong_password, no_identity_yet, unknown_user...).
void station_login(const std::string& username, Signer sign, LoginDone done, bool asked = false) {
  std::string dest_hex = net::status().dest_hex;
  auto ask = asked ? rpc::ask_now : [](const char* svc, const char* op, std::vector<waylink::Field> f,
                                        rpc::Callback cb, int attempts, uint32_t timeout_ms) {
    return rpc::ask(svc, op, std::move(f), std::move(cb), attempts, timeout_ms);
  };
  ask(
      "PROFILE", "LOGIN_NONCE", {Field::text("transport_dest", dest_hex)},
      [username, sign, done, dest_hex, ask](net::Result r, waylink::Reply& reply) {
        if (r != net::Result::Ok) {
          done(r, "", reply.error);
          return;
        }
        std::string nonce = reply.payload().bytes("nonce");
        // server/services/auth/pairing.py PairingService.login_bytes
        std::string msg = "WAYPOST-LOGIN-1\n" + net::status().node_id + "\n" + my_dest() + "\n" + nonce;
        std::string sig = sign(msg);
        ask("PROFILE", "LOGIN",
                  {Field::text("u", username), Field::bytes("rd", my_dest()), Field::bytes("sig", sig),
                   Field::text("transport_dest", dest_hex)},
                  [username, done](net::Result r, waylink::Reply& reply) {
                    done(r, reply.payload().text("display_name", username), reply.error);
                  },
                  1, 10000);
      },
      2, 8000);
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
    if (_working) return;  // working out the key / checking with Station
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

  // scrypt takes ~4 s: on the crypto worker, with the screen and keys alive.
  // By value: `password` is the prompt's own text, which is cleared below.
  void sign_in(std::string password) {
    _working = true;
    _prompt.clear();
    _prompt.set_note("Working out your key (about 5 seconds)...");
    std::string user = _user;
    tasks::run(tasks::Worker::Crypto, [this, user, pw = std::move(password)]() mutable {
      uint32_t t0 = millis();
      std::string seed = kdf::identity_seed(user, pw);
      std::fill(pw.begin(), pw.end(), '\0');
      Serial.printf("login: key in %lu ms\n", static_cast<unsigned long>(millis() - t0));
      tasks::post([this, seed] { got_seed(seed); });
    });
  }

  void got_seed(const std::string& seed) {
    _seed = seed;
    if (_seed.size() == 32) {
      // The public half's id (not secret: it's on the person's certificate),
      // to compare with Station's when a sign-in is refused.
      RNS::Cryptography::Ed25519PrivateKey key(bytes(_seed));
      std::string id = wp::identity_id_of(raw(key.public_key()->public_bytes()));
      Serial.printf("login: %s -> identity id %s\n", _user.c_str(), wp::hex(id).c_str());
    }
    if (_seed.size() != 32) {
      _working = false;
      _prompt.set_error("Not enough memory to work out the key - restart and try again.");
      return;
    }
    // Station first, even if it was marked quiet: the person is waiting, and
    // a password checked now beats one checked later. Offline sign-in only
    // when Station really doesn't answer.
    _prompt.set_note("Checking with Station...");
    std::string seed_copy = _seed;
    station_login(
        _user,
        [seed_copy](const std::string& msg) {
          RNS::Cryptography::Ed25519PrivateKey key(bytes(seed_copy));
          return raw(key.sign(bytes(msg)));
        },
        [this](net::Result r, const std::string& name, const std::string& error) {
          _working = false;
          if (r == net::Result::Error) {
            _prompt.set_error(explain(error));
            return;
          }
          if (r != net::Result::Ok) {
            offer_offline();
            return;
          }
          finish(_user, name, false);
        },
        /*asked=*/true);
  }

  // Signing in offline: the key is real if the password is; Station checks
  // it when it's next in reach (and signs this Scout out if it's wrong).
  void offer_offline() {
    _mode = Mode::Offline;
    Prompt::Options o;
    o.max_len = 3;
    _prompt.open(title(),
                 "Station didn't answer, so the password can't be checked yet. "
                 "Sign in anyway? Type YES (your messages wait until it's checked).",
                 o);
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
  bool _working = false;
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

namespace {

void whoami() {
  rpc::ask(
      "PROFILE", "WHOAMI", {Field::text("transport_dest", net::status().dest_hex)},
      [](net::Result r, waylink::Reply& reply) {
        if (r == net::Result::Ok) {
          g_identity_busy = false;
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
          return;
        }
        if (r == net::Result::Error && reply.error == "not_paired" && account::paired() &&
            certs::key_unlocked()) {
          // Signed in while Station was away (or unpaired from the portal):
          // the key is already worked out, so sign Station's challenge now.
          station_login(account::username(), certs::sign,
                        [](net::Result lr, const std::string& name, const std::string& error) {
                          g_identity_busy = false;
                          if (lr == net::Result::Ok) {
                            g_identity_settled = true;
                            account::set_user(account::username(), name);
                            Serial.println("identity: login finished with Station");
                          } else if (lr == net::Result::Error) {
                            g_identity_settled = true;
                            signed_out(explain(error) + " Sign in again.");
                          }
                        });
          return;
        }
        g_identity_busy = false;
        // not_paired with the key locked: wait for the next unlock.
        if (r == net::Result::Error && reply.error != "not_paired") g_identity_settled = true;
        // Timeouts: keep the cached account and try again later.
      },
      2, 8000);
}

}  // namespace

void apps::check_identity() {
  if (g_identity_busy) return;
  if (g_identity_settled && !account::unpair_pending()) return;
  if (!net::station_known()) return;
  if (g_identity_tried && millis() - g_identity_last_try < 60000) return;
  g_identity_tried = true;
  g_identity_last_try = millis();
  g_identity_busy = true;

  if (account::unpair_pending()) {
    // Finish a sign-out done on this Scout before asking who we are —
    // otherwise WHOAMI would hand the old account straight back.
    rpc::ask("PROFILE", "UNPAIR", {Field::text("transport_dest", net::status().dest_hex)},
              [](net::Result r, waylink::Reply&) {
                if (r != net::Result::Ok) {
                  g_identity_busy = false;  // try again in a minute
                  return;
                }
                account::clear_unpair_pending();
                Serial.println("identity: Station unpaired this Scout");
                whoami();
              },
              2, 8000);
    return;
  }
  whoami();
}
