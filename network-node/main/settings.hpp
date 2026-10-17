#pragma once
#include "core.hpp"
#include <atomic>

namespace netnode {
extern Settings settings; // Immutable after boot; settings changes reboot the device.
extern std::atomic<bool> online, gateway_ready, stopping;
extern std::atomic<bool> auth_blocked;
extern std::atomic<bool> setup_ap;
extern std::string ap_password;
std::string random_hex(size_t bytes);
void settings_load();
bool settings_save(const Settings &next, const std::string &setup_code);
bool verify_password(const std::string &password);
bool change_password(const std::string &password);
std::string enrollment_code();
void clear_enrollment();
void schedule_restart(bool factory_reset);
void network_invalidate();
void network_init();
void web_start();
void gateway_shutdown();
}
