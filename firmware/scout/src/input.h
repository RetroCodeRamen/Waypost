// Keyboard + trackball, one event stream. The UI task calls poll() every
// frame (~30 Hz): the keyboard controller holds one key, and nothing else
// ever keeps the UI task from reading it, so keys aren't lost.
#pragma once

#include <cstdint>

namespace input {

enum class Kind : uint8_t { None, Up, Down, Left, Right, Select, Enter, Backspace, Char };

struct Event {
  Kind kind = Kind::None;
  char ch = 0;
};

void init();     // after board::bring_up()
void poll();     // read the hardware into the queue (UI task, every frame)
bool next(Event& e);  // take the oldest queued event

}  // namespace input
