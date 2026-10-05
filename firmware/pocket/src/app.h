// Scout app framework — one app owns the screen at a time.
#pragma once

#include "input.h"
#include "store.h"
#include "waylink_cbor.h"

class App {
 public:
  virtual ~App() = default;
  virtual const char* title() const = 0;
  // Called when the app takes the screen; must draw everything.
  virtual void enter() = 0;
  virtual void on_event(const input::Event& e) = 0;
  // Called every loop() while active.
  virtual void tick() {}
};

namespace apps {

void open(App& app);
void home();
App* current();

App& home_app();
App& dispatch_app();
App& fieldbook_app();
App& trailhead_app();
App& signal_app();
App& login_app();  // username + password (replaced the pairing code, 2026-10-05)
App& lock_app();
App& settings_app();
App& beacon_app();

// Lock screen (when a PIN is set); unlocking returns to the app that was
// showing.
void lock();
bool locked();

// Asks Station which account this Scout is bound to (PROFILE/WHOAMI), once
// per boot as soon as Station is reachable: adopts the account if this
// Scout was bound elsewhere (portal/API), or drops a stale one if it was
// unpaired. Called from loop().
void check_identity();

// A live chat message pushed by Station: Dispatch records it, acks it, and
// counts it as unread when another app has the screen.
void deliver_chat(const waylink::IncomingChatMessage& msg);
// Fetch messages missed while out of range (DISPATCH/MSG_SYNC, paged).
void catch_up_chat();
// A message for this Scout's store from any source (push, catch-up, peer
// sync): saved, counted unread, shown if its conversation is open. True
// when it's new here.
bool deliver_message(const std::string& conv, const store::Message& m);
// Send the oldest queued Dispatch message if Station is in reach (one per
// call; waits between failed tries unless `force`).
void flush_outbox(bool force = false);

// A Beacon from Station (BEACON_ALERT push or BEACON_GET, compact form):
// shows the full-screen alert over any app, or closes it when cleared.
void beacon_event(const waylink::Value& compact);
bool beacon_showing();
// Ask Station for the active Beacon (an alert sent while we were away).
void check_beacon();
// Alerts are saved on the Scout (shown with Station out of reach; an
// acknowledged one isn't raised again after a reboot). load() before the
// radio starts; save() every loop (writes only when changed and safe).
void beacon_load();
void beacon_save();

}  // namespace apps
