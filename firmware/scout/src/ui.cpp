#include "ui.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include <Arduino.h>

#include "board.h"

namespace ui {
namespace {

bool g_station_ok = false;
int g_unread = 0;
std::string g_title;
// Text mirror of the screen for dump_to_serial().
std::string g_rows[kBodyLines];
int g_highlight_row = -1;
// What each body row last drew, so redrawing an unchanged row costs nothing
// (screens that refresh every second would otherwise resend the whole body).
struct Drawn {
  bool valid = false;
  uint16_t color = 0;
  bool highlight = false;
};
Drawn g_drawn[kBodyLines];
std::string g_footer;

constexpr int kSpinX = kWidth - 104;
constexpr int kSpinY = kTitleH / 2;
constexpr int kSpinR = 6;
constexpr int kSpinDots = 8;
int g_spin_step = -1;  // -1 = not shown
uint32_t g_spin_last_ms = 0;

lgfx::LGFX_Sprite& s() { return display::canvas(); }

const lgfx::IFont* font_of(int font) {
  switch (font) {
    case 1: return &fonts::Font0;
    case 4: return &fonts::Font4;
    default: return &fonts::Font2;
  }
}

// TFT_eSPI-style: draw `text` at x, y in numbered font `font`.
void text(const std::string& str, int x, int y, int font) {
  s().setFont(font_of(font));
  s().drawString(str.c_str(), x, y);
}

void draw_status() {
  s().fillRect(kWidth - 90, 0, 90, kTitleH - 1, kBar);
  s().setTextDatum(TR_DATUM);
  if (g_unread > 0) {
    s().setTextColor(kWarn, kBar);
    text("msg " + std::to_string(g_unread), kWidth - 26, 3, kFont);
  }
  s().fillCircle(kWidth - 12, kTitleH / 2, 5, g_station_ok ? kLive : kMuted);
  s().setTextDatum(TL_DATUM);
  mark_dirty(kWidth - 90, 0, 90, kTitleH);
}

void draw_spinner() {
  s().fillRect(kSpinX - kSpinR - 2, kSpinY - kSpinR - 2, 2 * kSpinR + 5, 2 * kSpinR + 5, kBar);
  if (g_spin_step >= 0) {
    for (int i = 0; i < kSpinDots; i++) {
      float a = i * 2.0f * PI / kSpinDots;
      int x = kSpinX + static_cast<int>(kSpinR * cosf(a));
      int y = kSpinY + static_cast<int>(kSpinR * sinf(a));
      int age = (g_spin_step - i + kSpinDots) % kSpinDots;
      uint16_t c = age == 0 ? kText : age < 3 ? kTextDim : kMuted;
      s().fillCircle(x, y, 1, c);
    }
  }
  mark_dirty(kSpinX - kSpinR - 2, kSpinY - kSpinR - 2, 2 * kSpinR + 5, 2 * kSpinR + 5);
}
}  // namespace

lgfx::LGFX_Sprite& tft() { return s(); }

int text_width(const std::string& str, int font) { return s().textWidth(str.c_str(), font_of(font)); }

// The T-Deck's backlight driver takes brightness as a count of pulses on its
// enable pin (16 steps; each low-high pulse steps one level down, wrapping),
// as in LilyGO's T-Deck examples. Low for a few ms switches it off.
static uint8_t g_brightness = kBrightnessMax;

void set_brightness(uint8_t level) {
  if (level > kBrightnessMax) level = kBrightnessMax;
  if (level == g_brightness) return;
  if (level == 0) {
    digitalWrite(board::kTftBacklight, LOW);
    delay(3);
    g_brightness = 0;
    return;
  }
  if (g_brightness == 0) {
    digitalWrite(board::kTftBacklight, HIGH);
    g_brightness = kBrightnessMax;
    delayMicroseconds(30);
  }
  int from = kBrightnessMax - g_brightness;
  int to = kBrightnessMax - level;
  int pulses = (kBrightnessMax + to - from) % kBrightnessMax;
  for (int i = 0; i < pulses; i++) {
    digitalWrite(board::kTftBacklight, LOW);
    digitalWrite(board::kTftBacklight, HIGH);
  }
  g_brightness = level;
}

uint8_t brightness() { return g_brightness; }

void init() {
  s().fillRect(0, 0, kWidth, kHeight, kBg);
  mark_dirty();
}

void mark_dirty(int x, int y, int w, int h) { display::mark(x, y, w, h); }

void mark_dirty() { display::mark_all(); }

void title_bar(const char* title) {
  g_title = title;
  s().fillRect(0, 0, kWidth, kTitleH - 1, kBar);
  s().drawFastHLine(0, kTitleH - 1, kWidth, kRule);
  s().setTextDatum(TL_DATUM);
  s().setTextColor(kText, kBar);
  text(title, kMargin, 3, kFont);
  mark_dirty(0, 0, kWidth, kTitleH);
  draw_status();
  if (g_spin_step >= 0) draw_spinner();
}

void set_station_ok(bool ok) {
  if (ok == g_station_ok) return;
  g_station_ok = ok;
  draw_status();
}

void set_unread(int n) {
  if (n == g_unread) return;
  g_unread = n;
  draw_status();
}

void animate(bool busy) {
  if (!busy) {
    if (g_spin_step < 0) return;
    g_spin_step = -1;
    draw_spinner();
    return;
  }
  uint32_t now = millis();
  if (g_spin_step >= 0 && now - g_spin_last_ms < 100) return;
  g_spin_last_ms = now;
  g_spin_step = (g_spin_step + 1) % kSpinDots;
  draw_spinner();
}

void clear_body() {
  s().fillRect(0, kTitleH, kWidth, kHeight - kTitleH, kBg);
  mark_dirty(0, kTitleH, kWidth, kHeight - kTitleH);
  for (auto& r : g_rows) r.clear();
  for (auto& d : g_drawn) d.valid = false;
  g_highlight_row = -1;
  g_footer.clear();
}

std::string to_display(const std::string& text) {
  std::string out;
  out.reserve(text.size());
  for (size_t i = 0; i < text.size();) {
    unsigned char c = static_cast<unsigned char>(text[i]);
    if (c < 0x80) {
      out.push_back(static_cast<char>(c));
      i++;
      continue;
    }
    size_t n = (c >= 0xF0) ? 4 : (c >= 0xE0) ? 3 : (c >= 0xC0) ? 2 : 1;
    std::string ch = text.substr(i, n);
    if (ch == "\xE2\x80\xA6") out += "...";
    else if (ch == "\xE2\x80\x94" || ch == "\xE2\x80\x93") out += "-";
    else if (ch == "\xE2\x80\x98" || ch == "\xE2\x80\x99") out += "'";
    else if (ch == "\xE2\x80\x9C" || ch == "\xE2\x80\x9D") out += "\"";
    else if (ch == "\xC2\xA0") out += " ";
    else out += "?";
    i += n;
  }
  return out;
}

void body_line(int row, const std::string& raw, uint16_t color, bool highlight) {
  const std::string text = to_display(raw);
  if (row >= 0 && row < kBodyLines) {
    Drawn& d = g_drawn[row];
    if (d.valid && d.color == color && d.highlight == highlight && g_rows[row] == text) return;
    d.valid = true;
    d.color = color;
    d.highlight = highlight;
    g_rows[row] = text;
    if (highlight) g_highlight_row = row;
    else if (g_highlight_row == row) g_highlight_row = -1;
  }
  int y = kBodyTop + row * kLineH;
  uint16_t bg = highlight ? kSelect : kBg;
  s().fillRect(0, y, kWidth, kLineH, bg);
  s().setTextDatum(TL_DATUM);
  s().setTextColor(highlight ? kText : color, bg);
  ui::text(text, kMargin, y + 1, kFont);
  mark_dirty(0, y, kWidth, kLineH);
}

void footer(const std::string& text, uint16_t color) {
  static uint16_t drawn_color = 0;
  if (text == g_footer && color == drawn_color && !g_footer.empty()) return;
  drawn_color = color;
  g_footer = text;
  s().fillRect(0, kBodyBottom, kWidth, kFooterH, kBg);
  s().drawFastHLine(0, kBodyBottom, kWidth, kRule);
  s().setTextDatum(TL_DATUM);
  s().setTextColor(color, kBg);
  ui::text(text, kMargin, kBodyBottom + 4, 1);
  mark_dirty(0, kBodyBottom, kWidth, kFooterH);
}

void message(const std::string& text, uint16_t color) {
  clear_body();
  auto lines = wrap(text);
  for (size_t i = 0; i < lines.size() && static_cast<int>(i) < kBodyLines; i++) {
    body_line(static_cast<int>(i) + 1, lines[i], color);
  }
}

std::vector<std::string> wrap(const std::string& raw, int width) {
  const std::string text = to_display(raw);
  std::vector<std::string> out;
  std::string line;
  auto fits = [&](const std::string& str) { return text_width(str) <= width; };

  size_t i = 0;
  while (i <= text.size()) {
    // Next word (up to a space/newline) — newlines force a break.
    size_t j = i;
    while (j < text.size() && text[j] != ' ' && text[j] != '\n') j++;
    std::string word = text.substr(i, j - i);

    std::string candidate = line.empty() ? word : line + " " + word;
    if (fits(candidate)) {
      line = candidate;
    } else {
      if (!line.empty()) out.push_back(line);
      line.clear();
      // A word wider than the screen: hard-break it.
      while (!fits(word) && word.size() > 1) {
        size_t cut = word.size() - 1;
        while (cut > 1 && !fits(word.substr(0, cut))) cut--;
        out.push_back(word.substr(0, cut));
        word = word.substr(cut);
      }
      line = word;
    }

    if (j >= text.size()) break;
    if (text[j] == '\n') {
      out.push_back(line);
      line.clear();
    }
    i = j + 1;
  }
  out.push_back(line);
  return out;
}

void list(const std::vector<std::string>& items, int selected, int& top) {
  if (selected < top) top = selected;
  if (selected >= top + kBodyLines) top = selected - kBodyLines + 1;
  if (top < 0) top = 0;
  for (int row = 0; row < kBodyLines; row++) {
    int idx = top + row;
    if (idx < static_cast<int>(items.size())) {
      body_line(row, items[idx], kTextDim, idx == selected);
    } else {
      body_line(row, "");
    }
  }
}

void pixels_to_serial() {
  // Full-resolution screenshot from the canvas: a text header, then
  // kWidth*kHeight RGB565 pixels as big-endian bytes, row by row.
  Serial.setTxTimeoutMs(200);  // a reader asked for it: let it block a little
  Serial.printf("=== raw %dx%d rgb565 ===\n", kWidth, kHeight);
  uint8_t row[kWidth * 2];
  for (int y = 0; y < kHeight; y++) {
    for (int x = 0; x < kWidth; x++) {
      uint16_t c = s().readPixel(x, y);
      row[2 * x] = c >> 8;
      row[2 * x + 1] = c & 0xFF;
    }
    Serial.write(row, sizeof(row));
  }
  Serial.println();
  Serial.println("=== end ===");
  Serial.flush();
  Serial.setTxTimeoutMs(0);
}

void mirror_row(int row, const std::string& text, bool highlight) {
  if (row < 0 || row >= kBodyLines) return;
  g_rows[row] = text;
  g_drawn[row].valid = false;  // drawn some other way
  if (highlight) g_highlight_row = row;
  else if (g_highlight_row == row) g_highlight_row = -1;
}

void dump_to_serial() {
  Serial.println("=== screen ===");
  std::string unread = g_unread > 0 ? " msg " + std::to_string(g_unread) : "";
  Serial.printf("[%s]%s%s\n", g_title.c_str(), g_station_ok ? " (station ok)" : "",
                unread.c_str());
  for (int i = 0; i < kBodyLines; i++) {
    Serial.printf("%c %s\n", i == g_highlight_row ? '>' : ' ', g_rows[i].c_str());
  }
  Serial.printf("-- %s\n", g_footer.c_str());
  Serial.println("=== end ===");
}

}  // namespace ui
