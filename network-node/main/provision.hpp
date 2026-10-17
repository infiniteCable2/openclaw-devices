#pragma once
#include <string>
#include "nvs.h"

namespace netnode {
// Separate from the resettable default NVS partition. Never auto-erase on error.
esp_err_t load_setup_password(nvs_handle_t legacy, std::string &password);
std::string setup_ssid();
void setup_console_start();
void setup_console_poll();
}
