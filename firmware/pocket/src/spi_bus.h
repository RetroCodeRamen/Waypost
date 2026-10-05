// The display and the LoRa radio share one SPI bus. While the radio starts
// on its own task (core 0), the UI may be drawing the boot screen (core 1);
// the radio driver re-initialises the bus (SPI.begin) and the display
// driver writes registers directly, so neither side's own locking stops a
// collision — and a collision can leave the panel ignoring every later
// update (frozen on the logo after a reset-button reboot, 2026-10-05).
// After start-up only the main loop touches either, so this is a boot-time
// guard.
#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

namespace spi_bus {

inline SemaphoreHandle_t handle() {
  static SemaphoreHandle_t m = xSemaphoreCreateMutex();
  return m;
}
inline bool try_lock() { return xSemaphoreTake(handle(), 0) == pdTRUE; }
inline void lock() { xSemaphoreTake(handle(), portMAX_DELAY); }
inline void unlock() { xSemaphoreGive(handle()); }

}  // namespace spi_bus
