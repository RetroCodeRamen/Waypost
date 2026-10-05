// Scout input — keyboard + trackball merged into one event stream.
#pragma once

#include <cstdint>

namespace input {

enum class Kind : uint8_t {
  None,
  Up,
  Down,
  Left,       // trackball left — apps treat it as Back
  Right,
  Select,     // trackball press
  Enter,      // keyboard Enter
  Backspace,  // keyboard Backspace/Delete
  Char,       // printable keyboard character in `ch`
};

struct Event {
  Kind kind = Kind::None;
  char ch = 0;
};

void init();
// Returns at most one event per call; Kind::None when idle.
Event poll();
// Read the keyboard/trackball into a queue without handling anything —
// called while the main loop waits on the radio, so keys typed meanwhile
// aren't lost (the keyboard controller holds only one).
void pump();
// millis() of the last key or trackball event (0 = none since boot).
uint32_t last_activity();

}  // namespace input
