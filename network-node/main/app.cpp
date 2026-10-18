#include "settings.hpp"
#include "provision.hpp"
#include "network.hpp"
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
static std::atomic<bool> lost_link{false};
static std::atomic<int64_t> retry_at{0};
static int64_t milliseconds() { return esp_timer_get_time() / 1000; }
static void apply_dns(esp_netif_t *station) {
    if (settings.dns.empty()) return;
    uint32_t address;
    ESP_ERROR_CHECK(ipv4(settings.dns, address) ? ESP_OK : ESP_ERR_INVALID_STATE);
    esp_netif_dns_info_t dns{};
    dns.ip.type = ESP_IPADDR_TYPE_V4;
    dns.ip.u_addr.ip4.addr = htonl(address);
    // All resolver slots use the selected server, including the SDK fallback.
    for (int slot = ESP_NETIF_DNS_MAIN; slot < ESP_NETIF_DNS_MAX; ++slot)
        ESP_ERROR_CHECK(esp_netif_set_dns_info(station, static_cast<esp_netif_dns_type_t>(slot), &dns));
}
static void wifi_event(void *, esp_event_base_t base, int32_t id, void *data) {
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        apply_dns(static_cast<ip_event_got_ip_t *>(data)->esp_netif);
        online = true;
    }
    else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        online = false; gateway_ready = false; network_invalidate();
        lost_link = true;
    }
}
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
static void configure_wifi() {
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta(); esp_netif_create_default_wifi_ap();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT(); ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, nullptr));
    wifi_config_t station{};
    std::memcpy(station.sta.ssid, settings.ssid.data(), settings.ssid.size());
    std::memcpy(station.sta.password, settings.wifi_password.data(), settings.wifi_password.size());
    station.sta.pmf_cfg.capable = true;
    wifi_config_t hotspot{};
    std::string ssid = setup_ssid();
    std::memcpy(hotspot.ap.ssid, ssid.c_str(), ssid.size() + 1);
    hotspot.ap.ssid_len = std::strlen(reinterpret_cast<char *>(hotspot.ap.ssid));
    std::memcpy(hotspot.ap.password, ap_password.data(), ap_password.size());
    hotspot.ap.channel = 1; hotspot.ap.max_connection = 2; hotspot.ap.authmode = WIFI_AUTH_WPA2_PSK;
    hotspot.ap.pmf_cfg.capable = true;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    if (!settings.ssid.empty()) ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &station));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &hotspot));
    setup_ap = settings.ssid.empty();
    ESP_ERROR_CHECK(esp_wifi_set_mode(setup_ap ? WIFI_MODE_APSTA : WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    if (!settings.ssid.empty()) esp_wifi_connect();
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL); esp_sntp_setservername(0, const_cast<char *>("pool.ntp.org")); esp_sntp_init();
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
    apply_dns(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"));
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
    configure_wifi(); setup_node(); web_start(); setup_console_start();
    gpio_config_t button{}; button.pin_bit_mask = 1ULL << board::factory_reset_pin;
    button.mode = GPIO_MODE_INPUT; button.pull_up_en = GPIO_PULLUP_ENABLE; ESP_ERROR_CHECK(gpio_config(&button));
    int64_t offline_since = milliseconds(), wifi_retry = 0, pressed_since = 0;
    while (!stopping) {
        int64_t now = milliseconds();
        if (lost_link.exchange(false)) {
            // A short Wi-Fi loss need not kill the underlying TCP socket.
            // Explicitly cancel it so saved-session reconnect cannot stay
            // blocked behind a still-ready native client after IP returns.
            xSemaphoreTake(gateway_mutex, portMAX_DELAY);
            if (node) esp_openclaw_node_request_disconnect(node);
            xSemaphoreGive(gateway_mutex);
        }
        if (online) {
            offline_since = now;
            if (setup_ap) { ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); setup_ap = false; }
        } else {
            if (!setup_ap && now - offline_since >= 30000) {
                ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA)); setup_ap = true;
            }
            if (!settings.ssid.empty() && now >= wifi_retry) { esp_wifi_connect(); wifi_retry = now + 10000; }
        }
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
