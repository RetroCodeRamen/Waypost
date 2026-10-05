#include "keyboard.h"

#include <Arduino.h>
#include <Wire.h>

#include "utilities.h"

namespace keyboard {

namespace {
constexpr uint8_t kKeyboardI2cAddress = 0x55;

bool g_present = false;
uint32_t g_misses = 0;
uint32_t g_last_probe = 0;

bool probe() {
  Wire.beginTransmission(kKeyboardI2cAddress);
  return Wire.endTransmission() == 0;
}

}  // namespace

void init() {
  // SDA/SCL already defined for this board in utilities.h; Wire isn't
  // otherwise in use yet (the TFT is SPI, the radio is SPI).
  Wire.begin(BOARD_I2C_SDA, BOARD_I2C_SCL);
  g_present = probe();
  Serial.printf("keyboard: %s\n", g_present ? "found" : "NOT answering at 0x55");
}

uint8_t poll() {
  // If the keyboard controller stopped answering (it restarts on its own
  // after a power dip), restart the bus and look again every 2 s.
  if (!g_present) {
    if (millis() - g_last_probe < 2000) return 0;
    g_last_probe = millis();
    Wire.end();
    Wire.begin(BOARD_I2C_SDA, BOARD_I2C_SCL);
    g_present = probe();
    if (g_present) Serial.println("keyboard: answering again");
    return 0;
  }
  uint8_t got = Wire.requestFrom(static_cast<uint8_t>(kKeyboardI2cAddress), static_cast<uint8_t>(1));
  if (got == 0) {
    if (++g_misses >= 20) {  // ~20 polls in a row with no answer
      g_present = false;
      g_misses = 0;
      Serial.println("keyboard: stopped answering - reconnecting");
    }
    return 0;
  }
  g_misses = 0;
  if (Wire.available() == 0) return 0;
  return static_cast<uint8_t>(Wire.read());
}

}  // namespace keyboard
