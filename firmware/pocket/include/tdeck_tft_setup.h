// TFT_eSPI pin/driver config for LilyGO T-Deck — from LilyGO's Setup210_LilyGo_T_Deck.h
// (Apache/MIT stack; vendored here so PlatformIO can -include it without forking TFT_eSPI).
#pragma once

#define USER_SETUP_LOADED
#define USER_SETUP_ID 210

#define ST7789_DRIVER
#define TFT_WIDTH 240
#define TFT_HEIGHT 320
// BGR: with TFT_RGB, blue-greens showed up olive on this panel (red and
// blue swapped: #0f2e3e displayed as ~#3e2e0f), reported 2026-10-03.
#define TFT_RGB_ORDER TFT_BGR
#define INIT_SEQUENCE_2

#define TFT_MISO 38
#define TFT_MOSI 41
#define TFT_SCLK 40
#define TFT_CS 12
#define TFT_DC 11
#define TFT_RST -1
#define TFT_BACKLIGHT_ON 1

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

// 27 MHz, not LilyGO's 40: the bus is shared with the LoRa radio and SD slot,
// and at 40 MHz large pushes intermittently failed to land (stale areas,
// dark right quarter), reported 2026-10-03.
#define SPI_FREQUENCY 27000000
#define SPI_READ_FREQUENCY 20000000
#define SPI_TOUCH_FREQUENCY 2500000
