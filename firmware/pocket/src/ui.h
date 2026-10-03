// Scout UI kit — TFT_eSPI helpers shared by every app (320x240, landscape).
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

TFT_eSPI& tft();
void init();

// Title bar: app name left; Station status + unread chat count right.
void title_bar(const char* title);
void set_station_ok(bool ok);
void set_unread(int n);

void clear_body();
// One line of body text at visual row `row` (0..kBodyLines-1).
void body_line(int row, const std::string& text, uint16_t color = TFT_LIGHTGREY,
               bool highlight = false);
void footer(const std::string& text, uint16_t color = TFT_DARKGREY);

// Full-body message, e.g. "Loading..." or an error.
void message(const std::string& text, uint16_t color = TFT_LIGHTGREY);

// Word-wrap to `width` pixels in kFont. Breaks long words. Never empty
// for non-empty input; an empty input yields one empty line.
std::vector<std::string> wrap(const std::string& text, int width = kWidth - 2 * kMargin);

// Scrolling list: keeps `selected` visible by adjusting `top`.
void list(const std::vector<std::string>& items, int selected, int& top);

// Prints the screen's text (title, body rows, footer) to Serial; the
// highlighted row is marked with '>'. For remote driving over USB.
void dump_to_serial();
// Records text for a row without drawing (for custom-drawn screens).
void mirror_row(int row, const std::string& text, bool highlight);

}  // namespace ui
