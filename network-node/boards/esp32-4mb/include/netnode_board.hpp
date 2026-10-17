#pragma once
#include "driver/gpio.h"

namespace netnode::board {
// Observed ESP32 board: BOOT pulls GPIO0 low. No PSRAM dependency.
inline constexpr gpio_num_t factory_reset_pin = GPIO_NUM_0;
}
