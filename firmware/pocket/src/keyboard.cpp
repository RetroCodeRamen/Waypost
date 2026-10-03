#include "keyboard.h"

#include <Arduino.h>
#include <Wire.h>

#include "utilities.h"

namespace keyboard {

namespace {
constexpr uint8_t kKeyboardI2cAddress = 0x55;
}

void init() {
  // SDA/SCL already defined for this board in utilities.h; Wire isn't
  // otherwise in use yet (the TFT is SPI, the radio is SPI).
  Wire.begin(BOARD_I2C_SDA, BOARD_I2C_SCL);
}

uint8_t poll() {
  Wire.requestFrom(static_cast<uint8_t>(kKeyboardI2cAddress), static_cast<uint8_t>(1));
  if (Wire.available() == 0) {
    return 0;
  }
  return static_cast<uint8_t>(Wire.read());
}

}  // namespace keyboard
