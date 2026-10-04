// Scout app framework — one app owns the screen at a time.
#pragma once

#include "input.h"
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
App& pairing_app();
App& lock_app();
App& settings_app();

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

}  // namespace apps
