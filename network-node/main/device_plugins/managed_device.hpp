#pragma once
#include "esp_netif.h"
#include "esp_openclaw_node.h"
#include <cstdint>
#include <string>

namespace netnode {
struct ManagedDeviceLink {
    esp_netif_t *interface = nullptr;
    esp_netif_ip_info_t ip{};
    uint8_t bssid[6]{};
    uint32_t generation = 0;

    bool current() const;
    bool contains(uint32_t address) const;
};

inline constexpr char managed_device_read[] = "network.device.read.v2";
void register_managed_device_plugins(esp_openclaw_node_handle_t node);
esp_err_t read_goe_status(const ManagedDeviceLink &link, const std::string &key, char **payload,
                          esp_openclaw_node_error_t *error);
esp_err_t managed_device_error(esp_openclaw_node_error_t *error, const char *code, const char *message,
                               esp_err_t status = ESP_ERR_INVALID_STATE);
}
