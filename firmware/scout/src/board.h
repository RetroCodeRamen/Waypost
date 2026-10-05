// LilyGO T-Deck pins and bring-up (docs/scout-firmware-architecture.md §3.8).
// Pin numbers as LilyGO's T-Deck examples / Meshtastic's t-deck variant.
#pragma once

#include <cstdint>

namespace board {

constexpr int kPowerOn = 10;       // peripheral power rail
constexpr int kSpiSck = 40, kSpiMiso = 38, kSpiMosi = 41;
constexpr int kTftCs = 12, kTftDc = 11, kTftBacklight = 42;
constexpr int kSdCs = 39;
constexpr int kRadioCs = 9, kRadioRst = 17, kRadioDio1 = 45, kRadioBusy = 13;
constexpr int kI2cSda = 18, kI2cScl = 8;
constexpr uint8_t kKeyboardAddress = 0x55;
constexpr int kTrackUp = 3, kTrackDown = 15, kTrackLeft = 1, kTrackRight = 2, kTrackPress = 0;

constexpr int kWidth = 320, kHeight = 240;  // landscape

// In LilyGO's order: power on, every chip-select high, MISO pulled up,
// SPI bus up, keyboard controller given time to start. Before any task.
void bring_up();

}  // namespace board
