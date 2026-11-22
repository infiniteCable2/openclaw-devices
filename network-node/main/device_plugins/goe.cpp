#include "goe_profile.hpp"
#include "device_network.hpp"
#include "core.hpp"
#include "esp_timer.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <memory>

namespace netnode {
namespace {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
constexpr uint32_t discovery_ms = 2500;
constexpr int64_t read_budget_us = 4500000;
constexpr int64_t address_hint_lifetime_us = 300000000;

struct AddressHint {
    char key[7]{};
    uint8_t bssid[6]{};
    uint32_t generation = 0;
    uint32_t local_address = 0;
    uint32_t netmask = 0;
    uint32_t address = 0;
    int64_t expires = 0;
};

// The native node invokes commands on its SDK task. Only that task uses these hints.
std::array<AddressHint, goe::max_devices_per_network> hints;

AddressHint &hint_for(const ManagedDeviceLink &link, const std::string &key) {
    for (auto &hint : hints) {
        if (hint.generation == link.generation && hint.local_address == link.ip.ip.addr &&
            hint.netmask == link.ip.netmask.addr && key == hint.key &&
            std::memcmp(hint.bssid, link.bssid, sizeof(hint.bssid)) == 0) return hint;
    }
    auto &slot = *std::min_element(hints.begin(), hints.end(), [](const AddressHint &a, const AddressHint &b) {
        return a.expires < b.expires;
    });
    slot = {};
    std::memcpy(slot.key, key.data(), key.size());
    std::memcpy(slot.bssid, link.bssid, sizeof(slot.bssid));
    slot.generation = link.generation;
    slot.local_address = link.ip.ip.addr;
    slot.netmask = link.ip.netmask.addr;
    return slot;
}

struct Discovery {
    const std::string &key;
    uint32_t verified = 0;
    uint32_t fallback = 0;
    bool conflicting = false;
    bool invalid_service = false;
    bool ambiguous = false;
};

bool inspect_service(const DnsSdService &service, void *context) {
    auto &result = *static_cast<Discovery *>(context);
    auto observation = goe::inspect(service.instance, service.port, service.txt, result.key);
    if (observation.match == goe::Match::serial_conflict) result.conflicting = true;
    if (observation.match == goe::Match::service_mismatch) result.invalid_service = true;
    if (observation.match != goe::Match::identified && observation.match != goe::Match::name_fallback)
        return true;
    uint32_t &selected = observation.match == goe::Match::identified ? result.verified : result.fallback;
    for (uint32_t address : service.addresses) {
        if (selected && selected != address) {
            result.ambiguous = true;
            return false;
        }
        selected = address;
    }
    return true;
}

struct ChargerAddress { uint32_t address; const char *error; };

ChargerAddress discover_charger(const ManagedDeviceLink &link, const std::string &key) {
    Discovery result{key};
    auto status = visit_local_services(link, goe::service, goe::protocol, discovery_ms, inspect_service, &result);
    if (status == DeviceNetworkError::wifi_changed) return {0, "GO_E_WIFI_CHANGED"};
    if (status != DeviceNetworkError::none) return {0, "GO_E_DISCOVERY_FAILED"};
    if (result.ambiguous) return {0, "GO_E_SERVICE_MISMATCH"};
    if (result.verified) return {result.verified, nullptr};
    if (result.conflicting) return {0, "GO_E_DISCOVERY_SERIAL_MISMATCH"};
    if (result.fallback) return {result.fallback, nullptr};
    return {0, result.invalid_service ? "GO_E_SERVICE_MISMATCH" : "GO_E_DISCOVERY_TIMEOUT"};
}

const cJSON *unique_field(const cJSON *object, const char *key) {
    const cJSON *result = nullptr;
    const cJSON *item;
    cJSON_ArrayForEach(item, object) {
        if (!item->string || std::strcmp(item->string, key)) continue;
        if (result) return nullptr;
        result = item;
    }
    return result;
}

esp_err_t read_identified_status(const ManagedDeviceLink &link, uint32_t address, const std::string &key,
                                 int64_t deadline, char **payload, esp_openclaw_node_error_t *error) {
    auto fail = [error](const char *code, const char *message) { return managed_device_error(error, code, message); };
    static const auto status_target = [] {
        std::string path = goe::status_path;
        for (const auto *field : goe::telemetry_fields) {
            path += ',';
            path += field;
        }
        return path;
    }();
    auto read = read_local_json(link, address, goe::port, status_target.c_str(), goe::status_max_bytes, deadline);
    if (!link.current() || read.error == DeviceNetworkError::wifi_changed)
        return fail("GO_E_WIFI_CHANGED", "The approved network changed");
    switch (read.error) {
    case DeviceNetworkError::unavailable:
        return fail("GO_E_HTTP_UNREACHABLE", "Incomplete charger status response");
    case DeviceNetworkError::timeout:
        return fail("GO_E_HTTP_TIMEOUT", "The charger status timed out");
    case DeviceNetworkError::rejected:
        return fail("GO_E_HTTP_REJECTED", "Charger status request rejected");
    case DeviceNetworkError::response_too_large:
        return fail("GO_E_INVALID_RESPONSE", "Charger status exceeds the allowed size");
    case DeviceNetworkError::wifi_changed:
    case DeviceNetworkError::none:
        break;
    }

    if (read.body.find("\\u0000") != std::string::npos)
        return fail("GO_E_INVALID_RESPONSE", "Charger status contains an invalid NUL escape");
    const char *end = nullptr;
    Json body(cJSON_ParseWithLengthOpts(read.body.c_str(), read.body.size() + 1, &end, true), cJSON_Delete);
    if (!cJSON_IsObject(body.get()) || end != read.body.c_str() + read.body.size())
        return fail("GO_E_INVALID_RESPONSE", "Charger status is not a valid object");
    const auto *serial = unique_field(body.get(), "sse");
    if (!cJSON_IsString(serial) || !serial->valuestring || key != serial->valuestring)
        return fail("GO_E_IDENTITY_MISMATCH", "The charger status did not confirm the approved serial");
    int state = 0, amps = 0;
    constexpr const char *states[] = {"unknown", "idle", "charging", "waitingForCar", "complete", "error"};
    Json reply(cJSON_CreateObject(), cJSON_Delete);
    if (!reply) return ESP_ERR_NO_MEM;
    if (!integer(body.get(), "car", 1, 5, state)) state = 0;
    cJSON_AddStringToObject(reply.get(), "chargingState", states[state]);
    cJSON_AddStringToObject(reply.get(), "deviceKey", key.c_str());
    const auto *allowed = unique_field(body.get(), "alw");
    if (cJSON_IsBool(allowed)) cJSON_AddBoolToObject(reply.get(), "chargingAllowed", cJSON_IsTrue(allowed));
    if (integer(body.get(), "acu", 0, 32, amps)) cJSON_AddNumberToObject(reply.get(), "allowedCurrentAmps", amps);
    auto *telemetry = cJSON_AddObjectToObject(reply.get(), "telemetry");
    if (!telemetry) return ESP_ERR_NO_MEM;
    for (const auto *field : goe::telemetry_fields) {
        const auto *value = unique_field(body.get(), field);
        if (!value) continue;
        auto *copy = cJSON_Duplicate(value, true);
        if (!copy || !cJSON_AddItemToObject(telemetry, field, copy)) {
            cJSON_Delete(copy);
            return ESP_ERR_NO_MEM;
        }
    }
    if (!link.current()) return fail("GO_E_WIFI_CHANGED", "The approved network changed");
    *payload = cJSON_PrintUnformatted(reply.get());
    return *payload ? ESP_OK : ESP_ERR_NO_MEM;
}
}

esp_err_t read_goe_status(const ManagedDeviceLink &link, const std::string &key, char **payload,
                          esp_openclaw_node_error_t *error) {
    if (!link.current()) return managed_device_error(error, "GO_E_WIFI_CHANGED", "The approved network changed");
    const int64_t now = esp_timer_get_time();
    const int64_t deadline = now + read_budget_us;
    auto &hint = hint_for(link, key);
    if (hint.expires > now && link.contains(hint.address)) {
        esp_openclaw_node_error_t cached_error{};
        auto status = read_identified_status(link, hint.address, key, now + 600000, payload, &cached_error);
        if (status == ESP_OK || status == ESP_ERR_NO_MEM) return status;
    }
    hint.address = 0;
    hint.expires = 0;
    if (!link.current()) return managed_device_error(error, "GO_E_WIFI_CHANGED", "The approved network changed");
    auto result = discover_charger(link, key);
    if (!result.address) return managed_device_error(error, result.error, "Cannot identify the approved go-e charger");
    auto status = read_identified_status(link, result.address, key, deadline, payload, error);
    if (status == ESP_OK) {
        hint.address = result.address;
        hint.expires = esp_timer_get_time() + address_hint_lifetime_us;
    }
    return status;
}
}
