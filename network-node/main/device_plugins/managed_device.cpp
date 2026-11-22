#include "managed_device.hpp"
#include "goe_profile.hpp"
#include "network.hpp"
#include "settings.hpp"
#include "esp_log.h"
#include "esp_wifi.h"
#include "lwip/inet.h"
#include "mdns.h"
#include <algorithm>
#include <cstring>
#include <iterator>
#include <memory>

namespace netnode {
namespace {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;

struct DevicePlugin {
    const char *id;
    bool Settings::*enabled;
    std::vector<std::string> WifiProfile::*approved_devices;
    bool (*valid_key)(std::string_view);
    esp_err_t (*read)(const ManagedDeviceLink &, const std::string &, char **, esp_openclaw_node_error_t *);
};

constexpr DevicePlugin plugins[] = {
    {goe::id, &Settings::goe_enabled, &WifiProfile::goe_devices, goe::valid_key, read_goe_status},
};

const WifiProfile *current_profile(const wifi_ap_record_t &ap) {
    auto ssid = std::string(reinterpret_cast<const char *>(ap.ssid));
    auto profile = std::find_if(settings.wifi_networks.begin(), settings.wifi_networks.end(),
                                [&ssid](const WifiProfile &entry) { return entry.ssid == ssid; });
    return profile == settings.wifi_networks.end() ? nullptr : &*profile;
}

esp_err_t read_device(esp_openclaw_node_handle_t, void *,
                      const esp_openclaw_node_command_invocation_t *invocation,
                      const char *raw, size_t length, char **payload, esp_openclaw_node_error_t *error) {
    if (!invocation || !invocation->session_key || !*invocation->session_key || stopping || !gateway_ready)
        return managed_device_error(error, "NOT_AUTHORIZED", "A live session-bound invocation is required");
    if (!raw || !payload || length > 128)
        return managed_device_error(error, "INVALID_ARGUMENT", "Expected one approved device key", ESP_ERR_INVALID_ARG);
    const std::string request(raw, length);
    if (request.find("\\u0000") != std::string::npos)
        return managed_device_error(error, "INVALID_ARGUMENT", "Device keys cannot contain NUL", ESP_ERR_INVALID_ARG);
    const char *end = nullptr;
    Json params(cJSON_ParseWithLengthOpts(request.c_str(), request.size() + 1, &end, true), cJSON_Delete);
    std::string plugin, key;
    if (!cJSON_IsObject(params.get()) || end != request.c_str() + request.size() ||
        cJSON_GetArraySize(params.get()) != 2 || !string_field(params.get(), "plugin", 24, plugin) ||
        !string_field(params.get(), "deviceKey", 48, key))
        return managed_device_error(error, "INVALID_ARGUMENT", "Expected a plugin ID and a device key", ESP_ERR_INVALID_ARG);
    const auto *selected = std::find_if(std::begin(plugins), std::end(plugins),
                                       [&plugin](const DevicePlugin &entry) { return plugin == entry.id; });
    if (selected == std::end(plugins) || !selected->valid_key(key))
        return managed_device_error(error, "INVALID_ARGUMENT", "Unsupported plugin or device key", ESP_ERR_INVALID_ARG);
    if (!(settings.*selected->enabled))
        return managed_device_error(error, "DEVICE_NOT_APPROVED", "Enable the device plugin in the node setup");

    ManagedDeviceLink link;
    link.generation = network_generation();
    link.interface = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    wifi_ap_record_t ap{};
    if (!online || setup_ap || !link.interface || esp_wifi_sta_get_ap_info(&ap) != ESP_OK ||
        esp_netif_get_ip_info(link.interface, &link.ip) != ESP_OK)
        return managed_device_error(error, "WIFI_UNAVAILABLE", "The node needs its approved station network");
    std::memcpy(link.bssid, ap.bssid, sizeof(link.bssid));
    auto *profile = current_profile(ap);
    if (!profile || profile->password.empty() || ap.authmode == WIFI_AUTH_OPEN || ap.authmode == WIFI_AUTH_WEP)
        return managed_device_error(error, "WIFI_NOT_APPROVED", "Use a saved protected node network");
    const auto &approved = profile->*selected->approved_devices;
    if (std::find(approved.begin(), approved.end(), key) == approved.end())
        return managed_device_error(error, "DEVICE_NOT_APPROVED", "Approve this device on the current node network");
    return selected->read(link, key, payload, error);
}
}

esp_err_t managed_device_error(esp_openclaw_node_error_t *error, const char *code, const char *message, esp_err_t status) {
    if (error) {
        error->code = code;
        error->message = message;
    }
    return status;
}

bool ManagedDeviceLink::current() const {
    if (stopping || !gateway_ready || !online || setup_ap || network_generation() != generation) return false;
    esp_netif_ip_info_t now{};
    wifi_ap_record_t ap{};
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK && esp_netif_get_ip_info(interface, &now) == ESP_OK &&
           now.ip.addr == ip.ip.addr && now.netmask.addr == ip.netmask.addr &&
           std::memcmp(ap.bssid, bssid, sizeof(bssid)) == 0 && network_generation() == generation;
}

bool ManagedDeviceLink::contains(uint32_t address) const {
    const uint32_t own = ntohl(ip.ip.addr), mask = ntohl(ip.netmask.addr);
    const bool private_address = (address >> 24) == 10 || (address >> 20) == 0xac1 || (address >> 16) == 0xc0a8;
    const uint32_t host_mask = ~mask, host = address & host_mask;
    return private_address && mask >= 0xff000000U && mask <= 0xfffffffcU &&
           (host_mask & (host_mask + 1)) == 0 && address != own &&
           (address & mask) == (own & mask) && host != 0 && host != host_mask &&
           (address & 0xffffff00U) != 0xc0a80400U;
}

void register_managed_device_plugins(esp_openclaw_node_handle_t node) {
    bool has_plugin = std::any_of(std::begin(plugins), std::end(plugins), [](const DevicePlugin &plugin) {
        return (settings.*plugin.enabled) && std::any_of(settings.wifi_networks.begin(), settings.wifi_networks.end(),
            [&plugin](const WifiProfile &profile) { return !(profile.*plugin.approved_devices).empty(); });
    });
    if (!has_plugin) return;
    if (mdns_init() != ESP_OK) {
        ESP_LOGW("managed-devices", "Local discovery unavailable");
        return;
    }
    esp_openclaw_node_command_v2_t command{};
    command.name = managed_device_read;
    command.handler = read_device;
    ESP_ERROR_CHECK(esp_openclaw_node_register_command_v2(node, &command));
}
}
