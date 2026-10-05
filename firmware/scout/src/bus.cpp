#include "bus.h"

namespace bus {

SemaphoreHandle_t lock_handle() {
  // Recursive: RadioLib may begin a transaction inside a sequence the
  // radio driver already holds the bus for (e.g. scan then receive).
  static SemaphoreHandle_t m = xSemaphoreCreateRecursiveMutex();
  return m;
}

}  // namespace bus
