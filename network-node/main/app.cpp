#include "settings.hpp"
#include "provision.hpp"
#include "network.hpp"
#include "wifi.hpp"
#include <cstring>
#include <cstdio>
#include <ctime>
#include "driver/gpio.h"
#include "netnode_board.hpp"
#include "bootloader_random.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "lwip/inet.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sodium.h"

namespace netnode {
static esp_openclaw_node_handle_t node;
static SemaphoreHandle_t gateway_mutex;
static std::atomic<bool> connecting{false};
static std::atomic<int64_t> retry_at{0};
static int64_t milliseconds() { return esp_timer_get_time() / 1000; }
static void node_event(esp_openclaw_node_handle_t, esp_openclaw_node_event_t event, const void *data, void *) {
    connecting = false;
    if (stopping) return;
    gateway_ready = false; network_invalidate();
    if (event == ESP_OPENCLAW_NODE_EVENT_CONNECTED) {
        auth_blocked = false; clear_enrollment(); gateway_ready = true;
    } else {
        if (event == ESP_OPENCLAW_NODE_EVENT_CONNECT_FAILED && data) {
            const auto *failed = static_cast<const esp_openclaw_node_connect_failed_event_t *>(data);
            if (failed->reason == ESP_OPENCLAW_NODE_CONNECT_FAILURE_AUTH_REJECTED) {
                const char *code = failed->gateway_detail_code;
                bool pending = code && (!std::strcmp(code, "PAIRING_REQUIRED") || !std::strcmp(code, "NOT_PAIRED"));
                auth_blocked = !pending;
            }
        }
        retry_at = milliseconds() + 10000;
    }
}
void gateway_shutdown() {
    xSemaphoreTake(gateway_mutex, portMAX_DELAY);
    if (node) { ESP_ERROR_CHECK(esp_openclaw_node_destroy(node)); node = nullptr; }
    xSemaphoreGive(gateway_mutex);
}
static void setup_node() {
    esp_openclaw_node_config_t config{}; esp_openclaw_node_config_init_default(&config);
    config.display_name = settings.context.c_str(); config.platform = "esp32"; config.device_family = "network-node";
    config.tls_cert_pem = settings.ca.empty() ? nullptr : settings.ca.c_str();
    config.use_cert_bundle = settings.ca.empty(); config.skip_cert_common_name_check = false; config.event_cb = node_event;
    ESP_ERROR_CHECK(esp_openclaw_node_create(&config, &node)); register_network_commands(node);
}
static void try_connect() {
    if (!online || gateway_ready || connecting || auth_blocked || settings.gateway.empty() ||
        stopping || milliseconds() < retry_at || std::time(nullptr) < 1704067200) return;
    xSemaphoreTake(gateway_mutex, portMAX_DELAY);
    if (stopping || !node) { xSemaphoreGive(gateway_mutex); return; }
    // DHCP can refresh DNS without changing the station IP. Reapply before
    // each explicit native connection request as well as on IP acquisition.
    wifi_apply_dns();
    std::string code = enrollment_code();
    esp_openclaw_node_connect_request_t request{};
    char *saved_uri = esp_openclaw_node_dup_gateway_uri(node);
    bool saved_matches = saved_uri && settings.gateway == saved_uri; free(saved_uri);
    if (!code.empty()) { request.source = ESP_OPENCLAW_NODE_CONNECT_SOURCE_SETUP_CODE; request.value = code.c_str(); }
    else if (saved_matches && esp_openclaw_node_has_saved_session(node)) request.source = ESP_OPENCLAW_NODE_CONNECT_SOURCE_SAVED_SESSION;
    else { xSemaphoreGive(gateway_mutex); return; }
    connecting = true;
    esp_err_t status = esp_openclaw_node_request_connect(node, &request);
    if (status != ESP_OK) { connecting = false; retry_at = milliseconds() + 10000; }
    xSemaphoreGive(gateway_mutex);
}
void run() {
    // NVS errors must not silently erase a paired identity or its settings.
    ESP_ERROR_CHECK(nvs_flash_init()); ESP_ERROR_CHECK(sodium_init() >= 0 ? ESP_OK : ESP_FAIL);
    // Provisioning secrets are created before the Wi-Fi radio supplies entropy.
    bootloader_random_enable(); settings_load(); bootloader_random_disable();
    network_init();
    gateway_mutex = xSemaphoreCreateMutex(); ESP_ERROR_CHECK(gateway_mutex ? ESP_OK : ESP_ERR_NO_MEM);
    wifi_start(); setup_node(); web_start(); setup_console_start();
    gpio_config_t button{}; button.pin_bit_mask = 1ULL << board::factory_reset_pin;
    button.mode = GPIO_MODE_INPUT; button.pull_up_en = GPIO_PULLUP_ENABLE; ESP_ERROR_CHECK(gpio_config(&button));
    int64_t pressed_since = 0;
    while (!stopping) {
        int64_t now = milliseconds();
        if (wifi_take_disconnect()) {
            // A short Wi-Fi loss need not kill the underlying TCP socket.
            // Explicitly cancel it so saved-session reconnect cannot stay
            // blocked behind a still-ready native client after IP returns.
            xSemaphoreTake(gateway_mutex, portMAX_DELAY);
            if (node) esp_openclaw_node_request_disconnect(node);
            xSemaphoreGive(gateway_mutex);
        }
        wifi_tick(now);
        if (!gpio_get_level(board::factory_reset_pin)) {
            if (!pressed_since) pressed_since = now;
            else if (now - pressed_since >= 10000) schedule_restart(true);
        } else pressed_since = 0;
        setup_console_poll(); try_connect(); vTaskDelay(pdMS_TO_TICKS(250));
    }
    vTaskDelete(nullptr);
}
}
extern "C" void app_main() { netnode::run(); }
