// Pairing — bind this Scout to a Station account with a 6-digit code from
// the portal (PROFILE/PAIR_REDEEM). No password ever crosses the radio.
#include <string>

#include <Arduino.h>

#include "account.h"
#include "app.h"
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

class PairingApp : public App {
 public:
  const char* title() const override { return "Pair this Scout"; }

  void enter() override {
    Prompt::Options opts;
    opts.digits_only = true;
    opts.max_len = 6;
    opts.allow_back = false;  // nothing useful works until paired
    _prompt.open(title(),
                 "On the Station portal open Devices and choose Pair a device, "
                 "then type the 6-digit code here.",
                 opts);
    if (!_note.empty()) _prompt.set_note(_note);
  }

  void on_event(const input::Event& e) override {
    if (_prompt.on_event(e) != Prompt::Result::Submitted) return;
    if (_prompt.value().size() != 6) {
      _prompt.set_error("The code is 6 digits.");
      return;
    }
    redeem(_prompt.value());
  }

  void set_note(const std::string& note) { _note = note; }

 private:
  void redeem(const std::string& code) {
    _prompt.set_note("Pairing...");
    waylink::Reply reply;
    auto r = station_link::request(
        "PROFILE", "PAIR_REDEEM",
        {Field::text("code", code), Field::text("node_id", station_link::node_id()),
         Field::text("transport_dest", station_link::dest_hex())},
        reply, 1, 15000);
    if (r == station_link::Result::Error) {
      _prompt.clear();
      _prompt.set_error("Station says: " + reply.error + ". Check the code and try again.");
      return;
    }
    if (r != station_link::Result::Ok) {
      _prompt.set_error(std::string("Couldn't reach Station (") + station_link::describe(r) +
                        "). Pairing needs Station in range.");
      return;
    }
    std::string username = reply.payload().text("username");
    account::set_user(username, username);
    account::clear_unpair_pending();  // a fresh pairing supersedes it
    _note.clear();
    g_identity_settled = g_identity_tried = false;  // next WHOAMI fetches the display name
    apps::home();
  }

  Prompt _prompt;
  std::string _note;
};

PairingApp& instance() {
  static PairingApp app;
  return app;
}

}  // namespace

App& apps::pairing_app() { return instance(); }

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
    // Finish an unpair done on this Scout before asking who we are —
    // otherwise WHOAMI would hand the old account straight back.
    if (station_link::request("PROFILE", "UNPAIR", {Field::text("transport_dest", station_link::dest_hex())}, reply, 2, 8000) != station_link::Result::Ok) {
      return;  // try again in a minute
    }
    account::clear_unpair_pending();
    Serial.println("identity: Station unpaired this Scout");
  }

  auto r = station_link::request("PROFILE", "WHOAMI", {Field::text("transport_dest", station_link::dest_hex())}, reply, 2, 8000);
  if (r == station_link::Result::Ok || r == station_link::Result::Error) g_identity_settled = true;
  if (r == station_link::Result::Ok) {
    std::string user = reply.payload().text("username");
    std::string name = reply.payload().text("display_name", user);
    bool adopted = !account::paired();
    if (user != account::username() || name != account::display_name()) {
      account::set_user(user, name);
    }
    Serial.printf("identity: %s (%s)\n", user.c_str(), adopted ? "adopted from Station" : "confirmed");
    if (adopted && apps::current() == &instance()) apps::home();
  } else if (r == station_link::Result::Error && reply.error == "not_paired") {
    if (account::paired()) {
      Serial.println("identity: Station says this Scout is no longer paired");
      account::unpair();
      instance().set_note("This Scout was unpaired on Station. Pair it again to continue.");
      apps::open(instance());
    }
  }
  // Timeouts: keep the cached account and try again on a later boot.
}
