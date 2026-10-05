// The screen: LovyanGFX driving the T-Deck's ST7789 (configuration as
// Meshtastic's t-deck build), apps draw into a canvas, and flush() sends
// only what changed — in short pieces from internal RAM, under the bus lock.
// Only the UI task touches any of this.
#pragma once

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

namespace display {

void init();                    // after board::bring_up()
lgfx::LGFX_Sprite& canvas();    // draw here (320x240, RGB565, PSRAM)
void mark(int x, int y, int w, int h);  // area changed
void mark_all();
void flush();                   // send marked areas to the panel
void set_backlight(bool on);

// Theme colours (the Waypost blue-greens: README header art, web portal).
uint16_t rgb(uint8_t r, uint8_t g, uint8_t b);

}  // namespace display
