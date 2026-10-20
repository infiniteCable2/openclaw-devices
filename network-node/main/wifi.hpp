#pragma once
#include "core.hpp"

namespace netnode {
void wifi_start();
void wifi_tick(int64_t now);
void wifi_apply_dns();
bool wifi_take_disconnect();
void wifi_status(cJSON *json);
bool wifi_scan_request(std::string &error);
cJSON *wifi_scan_status();
}
