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

// A live chat message pushed by Station: Dispatch records it, acks it, and
// counts it as unread when another app has the screen.
void deliver_chat(const waylink::IncomingChatMessage& msg);

}  // namespace apps
