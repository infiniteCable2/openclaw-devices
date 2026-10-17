#include "provision.hpp"
#include <cstdio>
#include <vector>
#include "esp_mac.h"
#include "esp_random.h"
#include "nvs_flash.h"

namespace netnode {
static esp_err_t read_password(nvs_handle_t handle, std::string &value) {
    size_t size = 0;
    esp_err_t result = nvs_get_str(handle, "ap_password", nullptr, &size);
    if (result != ESP_OK) return result;
    if (size != 25) return ESP_ERR_INVALID_SIZE;
    std::vector<char> buffer(size);
    result = nvs_get_str(handle, "ap_password", buffer.data(), &size);
    if (result != ESP_OK) return result;
    if (size != 25 || buffer[24] != '\0') return ESP_ERR_INVALID_SIZE;
    for (size_t i = 0; i < 24; ++i)
        if (!((buffer[i] >= '0' && buffer[i] <= '9') || (buffer[i] >= 'a' && buffer[i] <= 'f')))
            return ESP_ERR_INVALID_ARG;
    value.assign(buffer.data(), 24);
    return ESP_OK;
}
esp_err_t load_setup_password(nvs_handle_t legacy, std::string &password) {
    // Preserve corruption/version errors for recovery instead of invalidating stickers.
    esp_err_t result = nvs_flash_init_partition("provision");
    if (result != ESP_OK) return result;
    nvs_handle_t handle;
    result = nvs_open_from_partition("provision", "setup", NVS_READWRITE, &handle);
    if (result != ESP_OK) return result;
    std::string next;
    uint8_t version = 0;
    result = nvs_get_u8(handle, "version", &version);
    bool initialized = result == ESP_OK;
    if (initialized && version != 1) result = ESP_ERR_INVALID_STATE;
    if (result == ESP_ERR_NVS_NOT_FOUND) result = ESP_OK;
    if (result == ESP_OK) result = read_password(handle, next);
    bool needs_write = false;
    if (result == ESP_ERR_NVS_NOT_FOUND && initialized) {
        // NVS can discard a corrupt entry as missing. Never generate a replacement
        // on an already provisioned device, even after default NVS was reset.
        result = ESP_ERR_INVALID_STATE;
    } else if (result == ESP_ERR_NVS_NOT_FOUND) {
        // Migrate the existing device password before a reset can erase legacy NVS.
        result = read_password(legacy, next);
        if (result == ESP_ERR_NVS_NOT_FOUND) {
            uint8_t entropy[12];
            esp_fill_random(entropy, sizeof(entropy));
            for (uint8_t byte : entropy) {
                next += "0123456789abcdef"[byte >> 4];
                next += "0123456789abcdef"[byte & 15];
            }
            result = ESP_OK;
        }
        needs_write = result == ESP_OK;
    }
    if (result == ESP_OK && needs_write) result = nvs_set_str(handle, "ap_password", next.c_str());
    if (result == ESP_OK && !initialized) result = nvs_set_u8(handle, "version", 1);
    if (result == ESP_OK && (!initialized || needs_write)) result = nvs_commit(handle);
    nvs_close(handle);
    // No secret becomes usable until its durable write has succeeded.
    if (result == ESP_OK) password = next;
    return result;
}
std::string setup_ssid() {
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    char ssid[32];
    std::snprintf(ssid, sizeof(ssid), "OpenClaw-Setup-%02X%02X%02X", mac[3], mac[4], mac[5]);
    return ssid;
}
}
