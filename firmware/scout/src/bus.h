// The display and the LoRa radio share one SPI bus. One lock, taken by the
// radio around every SPI transaction (LockingHal, below) and by the display
// around every flush — Meshtastic's spiLock + LockingArduinoHal pattern.
// Without it, a display update and a radio transaction from the two tasks
// could interleave on the wire.
#pragma once

#include <Arduino.h>
#include <RadioLib.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

namespace bus {

SemaphoreHandle_t lock_handle();
inline void lock() { xSemaphoreTakeRecursive(lock_handle(), portMAX_DELAY); }
inline void unlock() { xSemaphoreGiveRecursive(lock_handle()); }

struct Guard {
  Guard() { lock(); }
  ~Guard() { unlock(); }
};

// RadioLib's Arduino HAL with the bus lock around every transaction.
class LockingHal : public ArduinoHal {
 public:
  LockingHal(SPIClass& spi, SPISettings settings) : ArduinoHal(spi, settings) {}
  void spiBeginTransaction() override {
    lock();
    ArduinoHal::spiBeginTransaction();
  }
  void spiEndTransaction() override {
    ArduinoHal::spiEndTransaction();
    unlock();
  }
};

}  // namespace bus
