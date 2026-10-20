#include "wifi.hpp"
#include "settings.hpp"
#include "provision.hpp"
#include "wifi_sdk.hpp"
#include <algorithm>
#include <cassert>
#include <cstring>
#include <iostream>
#include <memory>
using namespace netnode;
Settings netnode::settings;
std::atomic<bool> netnode::online{false}, netnode::gateway_ready{false}, netnode::stopping{false};
std::atomic<bool> netnode::auth_blocked{false}, netnode::setup_ap{false};
std::string netnode::ap_password = "synthetic-sticker-password";
std::string netnode::setup_ssid() { return "Setup-Example"; }
static int invalidations = 0;
void netnode::network_invalidate() { ++invalidations; }
static event_handler handler;
static esp_netif_t netif;
static wifi_config_t configured;
static wifi_mode_t mode;
static int64_t now = 1000;
static std::vector<std::string> attempts;
static std::vector<wifi_ap_record_t> records;
static uint32_t resolvers[DNS_MAX_SERVERS]{};
static int disconnects = 0, scans = 0, scan_stops = 0, clears = 0;
esp_err_t esp_event_loop_create_default() { return ESP_OK; }
esp_err_t esp_event_handler_register(esp_event_base_t, int32_t, event_handler fn, void *) { handler = fn; return ESP_OK; }
esp_err_t esp_netif_init() { return ESP_OK; }
esp_netif_t *esp_netif_create_default_wifi_sta() { return &netif; }
esp_netif_t *esp_netif_create_default_wifi_ap() { return &netif; }
esp_err_t esp_netif_set_dns_info(esp_netif_t *, esp_netif_dns_type_t slot, esp_netif_dns_info_t *dns) {
    // Match IDF's rejection of zero: only lwIP's owning task may clear slots.
    if (!dns->ip.u_addr.ip4.addr) return ESP_ERR_INVALID_ARG;
    resolvers[slot] = dns->ip.u_addr.ip4.addr; return ESP_OK;
}
esp_err_t esp_netif_tcpip_exec(esp_err_t (*fn)(void *), void *context) { return fn(context); }
void dns_setserver(int slot, const void *value) { assert(!value); resolvers[slot] = 0; }
void esp_sntp_setoperatingmode(int) {}
void esp_sntp_setservername(int, char *) {}
void esp_sntp_init() {}
int64_t esp_timer_get_time() { return now * 1000; }
SemaphoreHandle_t xSemaphoreCreateMutex() { return &netif; }
void xSemaphoreTake(SemaphoreHandle_t lock, int) { assert(lock); }
void xSemaphoreGive(SemaphoreHandle_t lock) { assert(lock); }
esp_err_t esp_wifi_init(wifi_init_config_t *) { return ESP_OK; }
esp_err_t esp_wifi_set_storage(int storage) { assert(storage == WIFI_STORAGE_RAM); return ESP_OK; }
esp_err_t esp_wifi_set_mode(wifi_mode_t next) { mode = next; return ESP_OK; }
esp_err_t esp_wifi_set_config(int interface, wifi_config_t *config) { if (interface == WIFI_IF_STA) configured = *config; return ESP_OK; }
esp_err_t esp_wifi_start() { return ESP_OK; }
static std::string ssid() { return std::string(reinterpret_cast<char *>(configured.sta.ssid), strnlen(reinterpret_cast<char *>(configured.sta.ssid), 32)); }
esp_err_t esp_wifi_connect() { attempts.push_back(ssid()); return ESP_OK; }
esp_err_t esp_wifi_disconnect() { ++disconnects; handler(nullptr, WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, nullptr); return ESP_OK; }
esp_err_t esp_wifi_scan_start(wifi_scan_config_t *config, bool blocking) { assert(!blocking && !config->show_hidden); ++scans; return ESP_OK; }
esp_err_t esp_wifi_scan_stop() { ++scan_stops; return ESP_OK; }
esp_err_t esp_wifi_clear_ap_list() { ++clears; records.clear(); return ESP_OK; }
esp_err_t esp_wifi_scan_get_ap_records(uint16_t *count, wifi_ap_record_t *out) {
    *count = std::min<size_t>(*count, records.size()); std::copy_n(records.begin(), *count, out); records.clear(); return ESP_OK;
}
esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *out) {
    std::memcpy(out->ssid, configured.sta.ssid, 32); out->rssi = -50; return ESP_OK;
}
static void tick(int elapsed = 0) { now += elapsed; wifi_tick(now); }
static void got_ip() { handler(nullptr, IP_EVENT, IP_EVENT_STA_GOT_IP, nullptr); }
static void scan_done(uint32_t status = 0) { wifi_event_sta_scan_done_t event{status}; handler(nullptr, WIFI_EVENT, WIFI_EVENT_SCAN_DONE, &event); tick(); }
static void ap(const char *name, int rssi, wifi_auth_mode_t auth) {
    wifi_ap_record_t record{}; std::strncpy(reinterpret_cast<char *>(record.ssid), name, 32);
    record.rssi = rssi; record.authmode = auth; records.push_back(record);
}
int main(int argc, char **) {
    if (argc > 1) {
        wifi_start(); tick(); assert(setup_ap && mode == WIFI_MODE_APSTA && attempts.empty());
        std::cout << "Empty profile list starts the setup AP\n"; return 0;
    }
    settings.ssid = "Hidden Example";
    settings.wifi_networks = {{"Example A", "", "", false}, {"Hidden Example", "example-password", "198.51.100.53", true}};
    wifi_start(); tick(); assert(attempts == std::vector<std::string>{"Hidden Example"});
    assert(configured.sta.threshold.authmode == WIFI_AUTH_WPA_PSK);
    got_ip(); uint32_t address; assert(ipv4("198.51.100.53", address));
    for (auto resolver : resolvers) assert(resolver == htonl(address));
    tick(); gateway_ready = true;
    esp_wifi_disconnect(); assert(!online && !gateway_ready && invalidations && wifi_take_disconnect() && !wifi_take_disconnect());
    tick(); tick(500); assert(attempts.back() == "Hidden Example"); // Retry current network first.
    tick(15000); tick(500); assert(attempts.back() == "Example A");
    assert(configured.sta.threshold.authmode == WIFI_AUTH_OPEN);
    for (auto resolver : resolvers) assert(resolver == 0); // No old custom DNS in DHCP profile.
    tick(14500); assert(setup_ap && mode == WIFI_MODE_APSTA);
    got_ip(); tick(); assert(!setup_ap && mode == WIFI_MODE_STA);
    std::string error;
    int before = disconnects;
    assert(wifi_scan_request(error)); tick(); tick(500);
    assert(scans == 1 && disconnects == before && online); // Connected scan keeps link.
    ap("Example A", -80, WIFI_AUTH_OPEN); ap("Example A", -45, WIFI_AUTH_OPEN);
    ap("Enterprise Example", -30, WIFI_AUTH_WPA2_ENTERPRISE); ap("", -20, WIFI_AUTH_OPEN);
    ap("bad\nSSID", -10, WIFI_AUTH_OPEN); scan_done();
    using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
    Json result(wifi_scan_status(), cJSON_Delete);
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(result.get(), "busy")));
    auto rows = cJSON_GetObjectItemCaseSensitive(result.get(), "networks");
    assert(cJSON_GetArraySize(rows) == 2);
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(cJSON_GetArrayItem(rows, 0), "supported")));
    assert(cJSON_GetObjectItemCaseSensitive(cJSON_GetArrayItem(rows, 1), "rssi")->valueint == -45);
    assert(!wifi_scan_request(error)); // Throttled even after a completed scan.
    tick(15000); assert(wifi_scan_request(error)); tick(); tick(500); scan_done(1);
    result.reset(wifi_scan_status()); assert(std::strlen(cJSON_GetObjectItemCaseSensitive(result.get(), "error")->valuestring) > 0 && clears == 1);
    tick(15000); assert(wifi_scan_request(error)); tick(); tick(500); tick(15000);
    assert(scan_stops == 1 && clears == 2);
    esp_wifi_disconnect(); tick(); tick(500); // Reconnect attempt, then offline scan.
    assert(wifi_scan_request(error)); tick(); tick(500); assert(scans == 4);
    scan_done(); tick(); tick(500); assert(attempts.size() >= 5);
    std::cout << "Real Wi-Fi manager: preferred/fallback/retry, AP recovery, per-WLAN DNS, async scan, deduplication, failure, timeout and rate limit passed\n";
}
