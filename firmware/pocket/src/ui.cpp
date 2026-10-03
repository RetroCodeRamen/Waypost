#include "ui.h"

#include <Arduino.h>

#include "utilities.h"

namespace ui {
namespace {
TFT_eSPI g_tft;
bool g_station_ok = false;
int g_unread = 0;
std::string g_title;
// Text mirror of the screen for dump_to_serial().
std::string g_rows[kBodyLines];
int g_highlight_row = -1;
std::string g_footer;

void draw_status() {
  g_tft.fillRect(kWidth - 90, 0, 90, kTitleH - 1, TFT_NAVY);
  g_tft.setTextDatum(TR_DATUM);
  if (g_unread > 0) {
    g_tft.setTextColor(TFT_YELLOW, TFT_NAVY);
    g_tft.drawString(("msg " + std::to_string(g_unread)).c_str(), kWidth - 26, 3, kFont);
  }
  g_tft.fillCircle(kWidth - 12, kTitleH / 2, 5, g_station_ok ? TFT_GREEN : TFT_DARKGREY);
  g_tft.setTextDatum(TL_DATUM);
}
}  // namespace

TFT_eSPI& tft() { return g_tft; }

void init() {
  pinMode(BOARD_TFT_BACKLIGHT, OUTPUT);
  digitalWrite(BOARD_TFT_BACKLIGHT, HIGH);
  g_tft.init();
  g_tft.setRotation(1);
  g_tft.fillScreen(TFT_BLACK);
}

void title_bar(const char* title) {
  g_title = title;
  g_tft.fillRect(0, 0, kWidth, kTitleH - 1, TFT_NAVY);
  g_tft.drawFastHLine(0, kTitleH - 1, kWidth, TFT_DARKGREY);
  g_tft.setTextDatum(TL_DATUM);
  g_tft.setTextColor(TFT_WHITE, TFT_NAVY);
  g_tft.drawString(title, kMargin, 3, kFont);
  draw_status();
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

void clear_body() {
  g_tft.fillRect(0, kTitleH, kWidth, kHeight - kTitleH, TFT_BLACK);
  for (auto& r : g_rows) r.clear();
  g_highlight_row = -1;
  g_footer.clear();
}

void body_line(int row, const std::string& text, uint16_t color, bool highlight) {
  if (row >= 0 && row < kBodyLines) {
    g_rows[row] = text;
    if (highlight) g_highlight_row = row;
    else if (g_highlight_row == row) g_highlight_row = -1;
  }
  int y = kBodyTop + row * kLineH;
  uint16_t bg = highlight ? TFT_DARKCYAN : TFT_BLACK;
  g_tft.fillRect(0, y, kWidth, kLineH, bg);
  g_tft.setTextDatum(TL_DATUM);
  g_tft.setTextColor(highlight ? TFT_WHITE : color, bg);
  g_tft.drawString(text.c_str(), kMargin, y + 1, kFont);
}

void footer(const std::string& text, uint16_t color) {
  g_footer = text;
  g_tft.fillRect(0, kBodyBottom, kWidth, kFooterH, TFT_BLACK);
  g_tft.drawFastHLine(0, kBodyBottom, kWidth, TFT_DARKGREY);
  g_tft.setTextDatum(TL_DATUM);
  g_tft.setTextColor(color, TFT_BLACK);
  g_tft.drawString(text.c_str(), kMargin, kBodyBottom + 4, 1);
}

void message(const std::string& text, uint16_t color) {
  clear_body();
  auto lines = wrap(text);
  for (size_t i = 0; i < lines.size() && static_cast<int>(i) < kBodyLines; i++) {
    body_line(static_cast<int>(i) + 1, lines[i], color);
  }
}

std::vector<std::string> wrap(const std::string& text, int width) {
  std::vector<std::string> out;
  std::string line;
  auto fits = [&](const std::string& s) { return g_tft.textWidth(s.c_str(), kFont) <= width; };

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
      body_line(row, items[idx], TFT_LIGHTGREY, idx == selected);
    } else {
      body_line(row, "");
    }
  }
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
