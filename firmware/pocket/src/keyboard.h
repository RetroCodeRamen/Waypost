// LilyGO T-Deck onboard keyboard — an ESP32-C3 co-processor that exposes
// keypresses over I2C at a fixed address (0x55 across LilyGO's own T-Deck
// examples and the wider T-Deck hobbyist ecosystem — same sourcing
// convention as utilities.h's own header comment). Needs live
// confirmation once flashed, same discipline as every other hardware
// fact in this project.
#pragma once

#include <cstdint>

namespace keyboard {

// Call once from setup(), after Wire/I2C pins are otherwise free to use
// (shares the bus with nothing else on this board today).
void init();

// Non-blocking: returns the next pressed key's ASCII byte, or 0 if
// nothing new is pending. Known values from the co-processor's own
// firmware: '\r' (0x0D) for Enter, 0x08 for Backspace, printable ASCII
// for everything else — treat any other control byte as a no-op.
uint8_t poll();

}  // namespace keyboard
