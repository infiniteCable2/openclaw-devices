#include "settings.hpp"
#include <cstdio>
#include <cstring>
#include "esp_random.h"
#include "esp_system.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "mbedtls/md.h"
#include "mbedtls/pkcs5.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

namespace netnode {
Settings settings;
std::atomic<bool> online{false}, gateway_ready{false}, stopping{false}, auth_blocked{false}, setup_ap{false};
std::string ap_password;
struct Credential { uint8_t salt[16]; uint8_t hash[32]; };
static Credential credential;
static SemaphoreHandle_t store_mutex;

std::string random_hex(size_t bytes) {
    std::string out;
    for (size_t i = 0; i < bytes; ++i) {
        uint8_t n = esp_random();
        out += "0123456789abcdef"[n >> 4]; out += "0123456789abcdef"[n & 15];
    }
    return out;
}
static bool derive(const std::string &password, const uint8_t *salt, uint8_t *hash) {
    return mbedtls_pkcs5_pbkdf2_hmac_ext(MBEDTLS_MD_SHA256,
        reinterpret_cast<const uint8_t *>(password.data()), password.size(), salt, 16, 20000, 32, hash) == 0;
}
bool verify_password(const std::string &password) {
    if (password.size() < 10 || password.size() > 72) return false;
    uint8_t candidate[32];
    if (!derive(password, credential.salt, candidate)) return false;
    unsigned difference = 0;
    for (size_t i = 0; i < sizeof(candidate); ++i) difference |= candidate[i] ^ credential.hash[i];
    std::memset(candidate, 0, sizeof(candidate));
    return difference == 0;
}
bool change_password(const std::string &password) {
    if (password.size() < 10 || password.size() > 72) return false;
    for (unsigned char c : password) if (c < 32 || c > 126) return false;
    Credential next;
    esp_fill_random(next.salt, sizeof(next.salt));
    if (!derive(password, next.salt, next.hash)) return false;
    nvs_handle_t handle;
    if (nvs_open("netnode", NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t status = nvs_set_blob(handle, "web_auth", &next, sizeof(next));
    if (status == ESP_OK) status = nvs_commit(handle);
    nvs_close(handle);
    if (status == ESP_OK) credential = next;
    return status == ESP_OK;
}
static std::string read_string(nvs_handle_t handle, const char *key, size_t maximum) {
    size_t size = 0;
    if (nvs_get_str(handle, key, nullptr, &size) != ESP_OK || size < 1 || size > maximum + 1) return "";
    std::vector<char> value(size);
    if (nvs_get_str(handle, key, value.data(), &size) != ESP_OK) return "";
    return value.data();
}
void settings_load() {
    store_mutex = xSemaphoreCreateMutex(); ESP_ERROR_CHECK(store_mutex ? ESP_OK : ESP_ERR_NO_MEM);
    nvs_handle_t handle;
    ESP_ERROR_CHECK(nvs_open("netnode", NVS_READWRITE, &handle));
    std::string stored = read_string(handle, "config", max_body);
    if (!stored.empty()) {
        cJSON *json = cJSON_Parse(stored.c_str());
        Settings next;
        std::string error;
        bool valid = parse_settings(json, settings, next, error);
        cJSON_Delete(json);
        // Corrupt settings never become permissive defaults.
        ESP_ERROR_CHECK(valid ? ESP_OK : ESP_ERR_INVALID_STATE);
        settings = next;
    }
    ap_password = read_string(handle, "ap_password", 63);
    if (ap_password.empty()) {
        ap_password = random_hex(12);
        ESP_ERROR_CHECK(nvs_set_str(handle, "ap_password", ap_password.c_str()));
    }
    size_t size = sizeof(credential);
    esp_err_t found = nvs_get_blob(handle, "web_auth", &credential, &size);
    ESP_ERROR_CHECK(nvs_commit(handle));
    nvs_close(handle);
    if (found == ESP_ERR_NVS_NOT_FOUND) {
        ESP_ERROR_CHECK(change_password(ap_password) ? ESP_OK : ESP_FAIL);
        // One-time serial provisioning output. Never print Gateway or Wi-Fi credentials.
        std::printf("\nOpenClaw network node initial setup\nUser: admin\nSetup Wi-Fi and initial web password: %s\n", ap_password.c_str());
    } else ESP_ERROR_CHECK(found == ESP_OK && size == sizeof(credential) ? ESP_OK : ESP_ERR_INVALID_STATE);
}
static bool store_config(const Settings &next, const std::string &setup_code) {
    cJSON *json = settings_json(next, true);
    if (!setup_code.empty()) cJSON_AddStringToObject(json, "enrollment", setup_code.c_str());
    char *raw = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);
    if (!raw) return false;
    nvs_handle_t handle;
    if (nvs_open("netnode", NVS_READWRITE, &handle) != ESP_OK) { free(raw); return false; }
    esp_err_t status = nvs_set_str(handle, "config", raw);
    free(raw);
    if (status == ESP_OK) status = nvs_commit(handle);
    nvs_close(handle);
    return status == ESP_OK;
}
std::string enrollment_code() {
    nvs_handle_t handle;
    if (nvs_open("netnode", NVS_READONLY, &handle) != ESP_OK) return "";
    std::string stored = read_string(handle, "config", max_body);
    nvs_close(handle);
    cJSON *json = cJSON_Parse(stored.c_str());
    std::string code;
    string_field(json, "enrollment", 2048, code);
    cJSON_Delete(json);
    return code;
}
bool settings_save(const Settings &next, const std::string &setup_code) {
    xSemaphoreTake(store_mutex, portMAX_DELAY);
    std::string code = setup_code.empty() && next.gateway == settings.gateway ? enrollment_code() : setup_code;
    bool saved = store_config(next, code);
    xSemaphoreGive(store_mutex);
    return saved;
}
void clear_enrollment() {
    xSemaphoreTake(store_mutex, portMAX_DELAY);
    nvs_handle_t handle;
    if (nvs_open("netnode", NVS_READWRITE, &handle) == ESP_OK) {
        // Edit the persisted object rather than the boot snapshot: a concurrent
        // local save may already contain the next boot's configuration.
        std::string stored = read_string(handle, "config", max_body);
        cJSON *json = cJSON_Parse(stored.c_str());
        std::string persisted_gateway;
        if (cJSON_IsObject(json) && string_field(json, "gateway", 256, persisted_gateway) && persisted_gateway == settings.gateway) {
            cJSON_DeleteItemFromObjectCaseSensitive(json, "enrollment");
            char *raw = cJSON_PrintUnformatted(json);
            if (raw) { ESP_ERROR_CHECK(nvs_set_str(handle, "config", raw)); ESP_ERROR_CHECK(nvs_commit(handle)); free(raw); }
        }
        cJSON_Delete(json); nvs_close(handle);
    }
    xSemaphoreGive(store_mutex);
}
static void restart_task(void *arg) {
    bool reset = arg != nullptr;
    vTaskDelay(pdMS_TO_TICKS(500));
    gateway_shutdown();
    network_invalidate();
    if (reset) ESP_ERROR_CHECK(nvs_flash_erase()); // Includes the native component's identity/session.
    esp_restart();
}
void schedule_restart(bool factory_reset) {
    if (stopping.exchange(true)) return;
    gateway_ready = false;
    ESP_ERROR_CHECK(xTaskCreate(restart_task, "node-restart", 3072,
        factory_reset ? reinterpret_cast<void *>(1) : nullptr, 6, nullptr) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}
}
