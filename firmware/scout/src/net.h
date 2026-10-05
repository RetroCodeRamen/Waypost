// The net task: everything Reticulum, on core 0. It owns the radio, the
// identity and every network job; nothing else calls microReticulum. The UI
// task talks to it only through commands (a queue) and reads a status
// snapshot — so no network work can ever hold up the screen or the keys
// (docs/scout-firmware-architecture.md §4).
//
// Milestone 1: bring-up plus a Station PING test (one, or a continuous
// flood to load the radio while watching the screen).
#pragma once

#include <cstdint>

#include "radio.h"

namespace net {

enum class Stage : uint8_t { Starting, Ready, Failed };

struct Status {
  Stage stage = Stage::Starting;
  const char* step = "starting";  // static strings only
  char dest[33] = {0};            // this Scout's destination hash (hex)
  bool station_path = false;
  bool flooding = false;
  uint32_t pings_sent = 0, pings_ok = 0, pings_lost = 0;
  uint32_t last_rtt_ms = 0;
  uint32_t loop_max_ms = 0;  // longest net-task pass in the last second
  radio::Stats radio;
};

enum class Command : uint8_t { Ping, ToggleFlood, Announce };

void start();                // after board::bring_up(); spawns the task
void send(Command c);        // from the UI task; never blocks
Status status();             // a copy, safe from any task

}  // namespace net
