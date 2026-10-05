// Scout UI kit — drawing helpers shared by every app (320x240, landscape).
//
// Everything draws into display.h's canvas (a full-screen sprite in PSRAM);
// the UI task flushes only the region that changed, once a frame. Only the
// UI task calls any of this.
#pragma once

#include <string>
#include <vector>

#include "display.h"

namespace ui {

constexpr int kWidth = 320;
constexpr int kHeight = 240;
constexpr int kFont = 2;          // font 2 (TFT_eSPI's, in LovyanGFX): 16 px tall
constexpr int kLineH = 18;
constexpr int kTitleH = 22;
constexpr int kFooterH = 16;
constexpr int kBodyTop = kTitleH + 2;
constexpr int kBodyBottom = kHeight - kFooterH;
constexpr int kBodyLines = (kBodyBottom - kBodyTop) / kLineH;  // 11
constexpr int kMargin = 4;

// -- Palette: the night-sky blue-greens of the README header art
// (image/logo2.png) and the logo (web/portal/static/brand/), sampled.
constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}
constexpr uint16_t kBg = rgb(0x0f, 0x2e, 0x3e);        // main sky, the blue-green
constexpr uint16_t kBar = rgb(0x06, 0x1c, 0x29);       // top of the sky, title bar
constexpr uint16_t kSelect = rgb(0x44, 0x7b, 0x88);    // glow behind the logo
constexpr uint16_t kBorder = rgb(0x2a, 0x55, 0x66);    // tile outlines
constexpr uint16_t kRule = rgb(0x19, 0x3c, 0x4d);      // dividers
constexpr uint16_t kText = rgb(0xf0, 0xf0, 0xe8);      // the path / logo cream
constexpr uint16_t kTextDim = rgb(0xc4, 0xd4, 0xcc);   // moon sage, lightened for body text
constexpr uint16_t kMuted = rgb(0x86, 0xa4, 0xa6);     // hints
constexpr uint16_t kLive = rgb(0x81, 0xbc, 0xaa);      // mint network nodes: links, connected
constexpr uint16_t kOk = rgb(0x81, 0xbc, 0xaa);        // same mint
constexpr uint16_t kWarn = rgb(0xd9, 0xa5, 0x4a);      // amber (portal), lifted for dark ground
constexpr uint16_t kError = rgb(0xe0, 0x6a, 0x5f);     // critical (portal), lifted

// The drawing surface (the canvas). Apps that draw directly must call
// mark_dirty() for the area they touched.
lgfx::LGFX_Sprite& tft();
void init();  // after display::init()
void mark_dirty(int x, int y, int w, int h);
void mark_dirty();  // whole screen
// Pixel width of `text` in font `font` (1, 2 or 4, as TFT_eSPI numbered them).
int text_width(const std::string& text, int font = kFont);

// Backlight, 0 (off) .. kBrightnessMax.
constexpr uint8_t kBrightnessMax = 16;
void set_brightness(uint8_t level);
uint8_t brightness();

// Title bar: app name left; Station status + unread chat count right.
void title_bar(const char* title);
void set_station_ok(bool ok);
void set_unread(int n);

// Busy spinner in the title bar while requests are out, so a slow radio
// wait never looks frozen. The UI task calls it every frame.
void animate(bool busy);

void clear_body();
// One line of body text at visual row `row` (0..kBodyLines-1).
void body_line(int row, const std::string& text, uint16_t color = kTextDim,
               bool highlight = false);
void footer(const std::string& text, uint16_t color = kMuted);

// Full-body message, e.g. "Loading..." or an error.
void message(const std::string& text, uint16_t color = kTextDim);

// The built-in fonts are ASCII only: map common UTF-8 punctuation (… — – ' ' " ")
// to ASCII and anything else to '?'. Applied by wrap() and body_line().
std::string to_display(const std::string& text);

// Word-wrap to `width` pixels in kFont. Breaks long words. Never empty
// for non-empty input; an empty input yields one empty line.
std::vector<std::string> wrap(const std::string& text, int width = kWidth - 2 * kMargin);

// Scrolling list: keeps `selected` visible by adjusting `top`.
void list(const std::vector<std::string>& items, int selected, int& top);

// Prints the screen's text (title, body rows, footer) to Serial; the
// highlighted row is marked with '>'. For remote driving over USB.
void dump_to_serial();
// Full-resolution screenshot from the canvas, as raw RGB565 over Serial
// (see ui.cpp for the framing). For remote debugging.
void pixels_to_serial();
// Records text for a row without drawing (for custom-drawn screens).
void mirror_row(int row, const std::string& text, bool highlight);

}  // namespace ui
