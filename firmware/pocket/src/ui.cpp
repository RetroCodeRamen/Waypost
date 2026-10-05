#include "ui.h"

#include "spi_bus.h"

#include <Arduino.h>

#include "utilities.h"

namespace ui {
namespace {
TFT_eSPI g_lcd;
TFT_eSprite g_canvas(&g_lcd);
TFT_eSPI* g_surface = &g_lcd;  // the canvas once created; the LCD as fallback
bool g_have_canvas = false;

// Union of areas drawn since the last present().
bool g_dirty = false;
int g_dx0 = 0, g_dy0 = 0, g_dx1 = 0, g_dy1 = 0;

bool g_station_ok = false;
int g_unread = 0;
std::string g_title;
// Text mirror of the screen for dump_to_serial().
std::string g_rows[kBodyLines];
int g_highlight_row = -1;
std::string g_footer;

constexpr int kSpinX = kWidth - 104;
constexpr int kSpinY = kTitleH / 2;
constexpr int kSpinR = 6;
constexpr int kSpinDots = 8;
int g_spin_step = -1;  // -1 = not shown
uint32_t g_spin_last_ms = 0;

TFT_eSPI& s() { return *g_surface; }

void draw_status() {
  s().fillRect(kWidth - 90, 0, 90, kTitleH - 1, kBar);
  s().setTextDatum(TR_DATUM);
  if (g_unread > 0) {
    s().setTextColor(kWarn, kBar);
    s().drawString(("msg " + std::to_string(g_unread)).c_str(), kWidth - 26, 3, kFont);
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

TFT_eSPI& tft() { return s(); }

// The T-Deck's backlight driver takes brightness as a count of pulses on its
// enable pin (16 steps; each low-high pulse steps one level down, wrapping),
// as in LilyGO's T-Deck examples. Low for a few ms switches it off.
static uint8_t g_brightness = kBrightnessMax;

void set_brightness(uint8_t level) {
  if (level > kBrightnessMax) level = kBrightnessMax;
  if (level == g_brightness) return;
  if (level == 0) {
    digitalWrite(BOARD_TFT_BACKLIGHT, LOW);
    delay(3);
    g_brightness = 0;
    return;
  }
  if (g_brightness == 0) {
    digitalWrite(BOARD_TFT_BACKLIGHT, HIGH);
    g_brightness = kBrightnessMax;
    delayMicroseconds(30);
  }
  int from = kBrightnessMax - g_brightness;
  int to = kBrightnessMax - level;
  int pulses = (kBrightnessMax + to - from) % kBrightnessMax;
  for (int i = 0; i < pulses; i++) {
    digitalWrite(BOARD_TFT_BACKLIGHT, LOW);
    digitalWrite(BOARD_TFT_BACKLIGHT, HIGH);
  }
  g_brightness = level;
}

uint8_t brightness() { return g_brightness; }

void init() {
  pinMode(BOARD_TFT_BACKLIGHT, OUTPUT);
  digitalWrite(BOARD_TFT_BACKLIGHT, HIGH);
  g_lcd.init();
  g_lcd.setRotation(1);
  g_lcd.fillScreen(kBg);

  g_canvas.setColorDepth(16);
  g_have_canvas = g_canvas.createSprite(kWidth, kHeight) != nullptr;  // ~150 KB, PSRAM
  if (g_have_canvas) {
    g_surface = &g_canvas;
  } else {
    Serial.println("ui: no memory for the screen canvas; drawing directly");
  }
  // Not fillScreen(): on the canvas sprite it fills the panel's native
  // 240-px width, leaving the rotated canvas's right 80 px black — the
  // "dark right quarter" reported 2026-10-03.
  s().fillRect(0, 0, kWidth, kHeight, kBg);
  mark_dirty();
}

void mark_dirty(int x, int y, int w, int h) {
  int x1 = x + w, y1 = y + h;
  if (x < 0) x = 0;
  if (y < 0) y = 0;
  if (x1 > kWidth) x1 = kWidth;
  if (y1 > kHeight) y1 = kHeight;
  if (x1 <= x || y1 <= y) return;
  if (!g_dirty) {
    g_dx0 = x, g_dy0 = y, g_dx1 = x1, g_dy1 = y1;
    g_dirty = true;
    return;
  }
  if (x < g_dx0) g_dx0 = x;
  if (y < g_dy0) g_dy0 = y;
  if (x1 > g_dx1) g_dx1 = x1;
  if (y1 > g_dy1) g_dy1 = y1;
}

void mark_dirty() { mark_dirty(0, 0, kWidth, kHeight); }

void present() {
  if (!g_dirty) return;
  if (!g_have_canvas) {
    g_dirty = false;
    return;  // already drawn straight to the LCD
  }
  // The radio task owns the shared SPI bus while it starts (spi_bus.h):
  // keep it dirty and push next time.
  if (!spi_bus::try_lock()) return;
  g_dirty = false;
  // Push row by row ourselves rather than via pushSprite(): its fast path
  // (one block push for full-width regions) never reached this panel —
  // only narrower, line-by-line pushes refreshed, leaving stale areas and
  // a dark right quarter (reported 2026-10-03). Even x/width keeps each
  // row's start 4-byte aligned for TFT_eSPI's 32-bit pixel copy.
  int x0 = g_dx0 & ~1;
  int w = ((g_dx1 - x0) + 1) & ~1;
  if (x0 + w > kWidth) w = kWidth - x0;
  uint16_t* buf = static_cast<uint16_t*>(g_canvas.getPointer());
  bool swap = g_lcd.getSwapBytes();
  g_lcd.setSwapBytes(false);  // the sprite already stores panel byte order
  g_lcd.startWrite();
  for (int y = g_dy0; y < g_dy1; y++) {
    g_lcd.pushImage(x0, y, w, 1, buf + y * kWidth + x0);
  }
  g_lcd.endWrite();
  g_lcd.setSwapBytes(swap);
  spi_bus::unlock();
}

void reinit_panel() {
  // Re-send the panel's init sequence, then redraw everything: clears any
  // state a bus collision or a reset-button power dip left it in.
  if (!spi_bus::try_lock()) return;
  g_lcd.init();
  g_lcd.setRotation(1);
  spi_bus::unlock();
  mark_dirty();
  present();
}

void title_bar(const char* title) {
  g_title = title;
  s().fillRect(0, 0, kWidth, kTitleH - 1, kBar);
  s().drawFastHLine(0, kTitleH - 1, kWidth, kRule);
  s().setTextDatum(TL_DATUM);
  s().setTextColor(kText, kBar);
  s().drawString(title, kMargin, 3, kFont);
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

void busy_tick() {
  uint32_t now = millis();
  if (g_spin_step >= 0 && now - g_spin_last_ms < 100) return;
  g_spin_last_ms = now;
  g_spin_step = (g_spin_step + 1) % kSpinDots;
  draw_spinner();
  present();  // the main loop isn't running during a blocking wait
}

void busy_clear() {
  if (g_spin_step < 0) return;
  g_spin_step = -1;
  draw_spinner();
  present();
}

void clear_body() {
  s().fillRect(0, kTitleH, kWidth, kHeight - kTitleH, kBg);
  mark_dirty(0, kTitleH, kWidth, kHeight - kTitleH);
  for (auto& r : g_rows) r.clear();
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
    g_rows[row] = text;
    if (highlight) g_highlight_row = row;
    else if (g_highlight_row == row) g_highlight_row = -1;
  }
  int y = kBodyTop + row * kLineH;
  uint16_t bg = highlight ? kSelect : kBg;
  s().fillRect(0, y, kWidth, kLineH, bg);
  s().setTextDatum(TL_DATUM);
  s().setTextColor(highlight ? kText : color, bg);
  s().drawString(text.c_str(), kMargin, y + 1, kFont);
  mark_dirty(0, y, kWidth, kLineH);
}

void footer(const std::string& text, uint16_t color) {
  g_footer = text;
  s().fillRect(0, kBodyBottom, kWidth, kFooterH, kBg);
  s().drawFastHLine(0, kBodyBottom, kWidth, kRule);
  s().setTextDatum(TL_DATUM);
  s().setTextColor(color, kBg);
  s().drawString(text.c_str(), kMargin, kBodyBottom + 4, 1);
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
  auto fits = [&](const std::string& str) { return s().textWidth(str.c_str(), kFont) <= width; };

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
  if (!g_have_canvas) {
    Serial.println("=== raw: no canvas ===");
    return;
  }
  // main.cpp sets a 0 ms TX timeout so an unread port never stalls the
  // UI; a screenshot is only requested by a reader, so let it block.
  Serial.setTxTimeoutMs(200);
  Serial.printf("=== raw %dx%d rgb565 ===\n", kWidth, kHeight);
  uint8_t row[kWidth * 2];
  for (int y = 0; y < kHeight; y++) {
    for (int x = 0; x < kWidth; x++) {
      uint16_t c = g_canvas.readPixel(x, y);
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
