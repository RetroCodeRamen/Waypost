// Scout UI kit — TFT_eSPI helpers shared by every app (320x240, landscape).
//
// Everything draws into an off-screen canvas (a full-screen sprite in PSRAM)
// and present() pushes only the region that changed. Fills happen in RAM,
// so they can't be lost on the bus the display shares with the LoRa radio,
// redraws don't flicker, and the canvas can be read back for debugging.
#pragma once

#include <string>
#include <vector>

#include <TFT_eSPI.h>

namespace ui {

constexpr int kWidth = 320;
constexpr int kHeight = 240;
constexpr int kFont = 2;          // TFT_eSPI font 2: 16 px tall
constexpr int kLineH = 18;
constexpr int kTitleH = 22;
constexpr int kFooterH = 16;
constexpr int kBodyTop = kTitleH + 2;
constexpr int kBodyBottom = kHeight - kFooterH;
constexpr int kBodyLines = (kBodyBottom - kBodyTop) / kLineH;  // 11
constexpr int kMargin = 4;

// -- Palette: the portal's design tokens (web/portal/static/tokens.css) ------
constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}
constexpr uint16_t kBg = rgb(0x11, 0x24, 0x20);        // --wp-sidebar-end, deep forest
constexpr uint16_t kBar = rgb(0x1f, 0x41, 0x47);       // --wp-teal-dark, title bar
constexpr uint16_t kSelect = rgb(0x2b, 0x80, 0x78);    // --wp-aqua-deep, selection
constexpr uint16_t kBorder = rgb(0x2d, 0x5a, 0x42);    // --wp-green, outlines
constexpr uint16_t kRule = rgb(0x1e, 0x40, 0x38);      // --wp-sidebar-active, dividers
constexpr uint16_t kText = rgb(0xf4, 0xf6, 0xf2);      // --wp-path, headings/selected
constexpr uint16_t kTextDim = rgb(0xbc, 0xcd, 0xc5);   // --wp-moon, body text
constexpr uint16_t kMuted = rgb(0x8a, 0x94, 0x8c);     // --wp-stone, hints
constexpr uint16_t kLive = rgb(0x3f, 0xa7, 0x9d);      // --wp-aqua, links / connected
constexpr uint16_t kOk = rgb(0x3f, 0xa6, 0x6b);        // --wp-positive
constexpr uint16_t kWarn = rgb(0xc9, 0x92, 0x3a);      // --wp-amber
constexpr uint16_t kError = rgb(0xb8, 0x45, 0x40);     // --wp-critical

// The drawing surface (the canvas). Apps that draw directly must call
// mark_dirty() for the area they touched.
TFT_eSPI& tft();
void init();
void mark_dirty(int x, int y, int w, int h);
void mark_dirty();  // whole screen
// Pushes changed pixels to the display. main loop() calls it every pass;
// busy_tick() calls it during blocking waits.
void present();

// Title bar: app name left; Station status + unread chat count right.
void title_bar(const char* title);
void set_station_ok(bool ok);
void set_unread(int n);

// Busy spinner in the title bar, so a slow radio wait never looks frozen.
// busy_tick() is safe to call in tight loops (redraws at most ~10x/s).
void busy_tick();
void busy_clear();

void clear_body();
// One line of body text at visual row `row` (0..kBodyLines-1).
void body_line(int row, const std::string& text, uint16_t color = kTextDim,
               bool highlight = false);
void footer(const std::string& text, uint16_t color = kMuted);

// Full-body message, e.g. "Loading..." or an error.
void message(const std::string& text, uint16_t color = kTextDim);

// Word-wrap to `width` pixels in kFont. Breaks long words. Never empty
// for non-empty input; an empty input yields one empty line.
std::vector<std::string> wrap(const std::string& text, int width = kWidth - 2 * kMargin);

// Scrolling list: keeps `selected` visible by adjusting `top`.
void list(const std::vector<std::string>& items, int selected, int& top);

// Prints the screen's text (title, body rows, footer) to Serial; the
// highlighted row is marked with '>'. For remote driving over USB.
void dump_to_serial();
// Coarse screenshot from the canvas: one character per sample, palette
// legend in ui.cpp. For remote debugging.
void pixels_to_serial();
// Records text for a row without drawing (for custom-drawn screens).
void mirror_row(int row, const std::string& text, bool highlight);

}  // namespace ui
