#include "display.h"

#include <algorithm>
#include <cstring>

#include <Arduino.h>

#include "board.h"
#include "bus.h"

namespace display {
namespace {

class Panel : public lgfx::LGFX_Device {
  lgfx::Panel_ST7789 _panel;
  lgfx::Bus_SPI _bus;

 public:
  Panel() {
    {
      auto cfg = _bus.config();
      cfg.spi_host = SPI2_HOST;
      cfg.spi_mode = 0;
      cfg.freq_write = 40000000;  // as LilyGO's and Meshtastic's T-Deck setups
      cfg.freq_read = 16000000;
      cfg.spi_3wire = false;
      cfg.use_lock = true;
      cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = board::kSpiSck;
      cfg.pin_mosi = board::kSpiMosi;
      cfg.pin_miso = board::kSpiMiso;
      cfg.pin_dc = board::kTftDc;
      _bus.config(cfg);
      _panel.setBus(&_bus);
    }
    {
      auto cfg = _panel.config();
      cfg.pin_cs = board::kTftCs;
      cfg.pin_rst = -1;
      cfg.pin_busy = -1;
      cfg.memory_width = 240;
      cfg.memory_height = 320;
      cfg.panel_width = 240;
      cfg.panel_height = 320;
      cfg.offset_x = 0;
      cfg.offset_y = 0;
      cfg.offset_rotation = 0;
      cfg.readable = false;
      cfg.invert = true;     // Meshtastic t-deck
      cfg.rgb_order = false;
      cfg.dlen_16bit = false;
      cfg.bus_shared = true;  // the radio is on this bus
      _panel.config(cfg);
    }
    setPanel(&_panel);
  }
};

Panel g_lcd;
lgfx::LGFX_Sprite g_canvas(&g_lcd);
bool g_dirty = false;
int g_x0 = 0, g_y0 = 0, g_x1 = 0, g_y1 = 0;  // dirty rectangle [x0,x1) x [y0,y1)

constexpr int kChunkRows = 8;
uint16_t g_chunk[board::kWidth * kChunkRows];  // internal RAM, DMA-capable

}  // namespace

uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) { return lgfx::color565(r, g, b); }

void init() {
  pinMode(board::kTftBacklight, OUTPUT);
  {
    bus::Guard g;
    g_lcd.init();
    g_lcd.setRotation(1);  // landscape, keyboard below
    g_lcd.fillScreen(TFT_BLACK);
  }
  set_backlight(true);
  g_canvas.setPsram(true);
  g_canvas.setColorDepth(16);
  if (!g_canvas.createSprite(board::kWidth, board::kHeight)) {
    Serial.println("display: no memory for the canvas");
  }
  g_canvas.fillScreen(TFT_BLACK);
  mark_all();
}

lgfx::LGFX_Sprite& canvas() { return g_canvas; }

void mark(int x, int y, int w, int h) {
  int x1 = std::min(board::kWidth, x + w), y1 = std::min(board::kHeight, y + h);
  x = std::max(0, x);
  y = std::max(0, y);
  if (x1 <= x || y1 <= y) return;
  if (!g_dirty) {
    g_x0 = x, g_y0 = y, g_x1 = x1, g_y1 = y1;
    g_dirty = true;
    return;
  }
  g_x0 = std::min(g_x0, x), g_y0 = std::min(g_y0, y);
  g_x1 = std::max(g_x1, x1), g_y1 = std::max(g_y1, y1);
}

void mark_all() { mark(0, 0, board::kWidth, board::kHeight); }

void flush() {
  if (!g_dirty) return;
  g_dirty = false;
  const int w = g_x1 - g_x0;
  const auto* src = static_cast<const uint16_t*>(g_canvas.getBuffer());
  bus::Guard g;  // the whole flush: no radio transaction in between
  g_lcd.startWrite();
  for (int y = g_y0; y < g_y1; y += kChunkRows) {
    int rows = std::min(kChunkRows, g_y1 - y);
    for (int r = 0; r < rows; r++)
      memcpy(g_chunk + r * w, src + (y + r) * board::kWidth + g_x0, w * sizeof(uint16_t));
    // The sprite stores pixels in the panel's byte order already.
    g_lcd.pushImage(g_x0, y, w, rows, reinterpret_cast<lgfx::swap565_t*>(g_chunk));
  }
  g_lcd.endWrite();
}

void set_backlight(bool on) { digitalWrite(board::kTftBacklight, on ? HIGH : LOW); }

}  // namespace display
