#include "wifi.hpp"
#include "settings.hpp"
#include "provision.hpp"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <memory>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "lwip/inet.h"
#include "lwip/dns.h"

namespace netnode {
static esp_netif_t *station;
static std::atomic<int> active{-1};
static std::atomic<bool> lost_link{false}, scan_done{false}, scan_failed{false};
static SemaphoreHandle_t scan_mutex;
struct Seen { std::string ssid, security; int rssi; bool supported; };
static std::vector<Seen> seen;
static std::string scan_error;
static bool scan_pending = false; // Protected by scan_mutex, including HTTP access.
static int64_t last_scan = -15000;
// The main task alone drives connection attempts and scans.
static int next_index = 0;
static int64_t attempt_until = 0, offline_since = 0, scan_started = 0, resume_at = 0;
static bool was_online = false, scanning = false, preparing_scan = false;
static int64_t milliseconds() { return esp_timer_get_time() / 1000; }

void wifi_apply_dns() {
    int index = active.load();
    if (index < 0 || size_t(index) >= settings.wifi_networks.size()) return;
    const auto &profile = settings.wifi_networks[index];
    if (profile.dns.empty()) return;
    uint32_t address;
    ESP_ERROR_CHECK(ipv4(profile.dns, address) ? ESP_OK : ESP_ERR_INVALID_STATE);
    esp_netif_dns_info_t dns{};
    dns.ip.type = ESP_IPADDR_TYPE_V4; dns.ip.u_addr.ip4.addr = htonl(address);
    for (int slot = ESP_NETIF_DNS_MAIN; slot < ESP_NETIF_DNS_MAX; ++slot)
        ESP_ERROR_CHECK(esp_netif_set_dns_info(station, static_cast<esp_netif_dns_type_t>(slot), &dns));
}
static void event(void *, esp_event_base_t base, int32_t id, void *data) {
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) { wifi_apply_dns(); online = true; }
    else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        online = false; gateway_ready = false; network_invalidate(); lost_link = true;
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        scan_failed = !data || static_cast<wifi_event_sta_scan_done_t *>(data)->status != 0;
        scan_done = true;
    }
}
bool wifi_take_disconnect() { return lost_link.exchange(false); }
void wifi_start() {
    scan_mutex = xSemaphoreCreateMutex(); ESP_ERROR_CHECK(scan_mutex ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    station = esp_netif_create_default_wifi_sta(); esp_netif_create_default_wifi_ap();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT(); ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, event, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, event, nullptr));
    wifi_config_t hotspot{};
    std::string ssid = setup_ssid();
    std::memcpy(hotspot.ap.ssid, ssid.data(), ssid.size()); hotspot.ap.ssid_len = ssid.size();
    std::memcpy(hotspot.ap.password, ap_password.data(), ap_password.size());
    hotspot.ap.channel = 1; hotspot.ap.max_connection = 2; hotspot.ap.authmode = WIFI_AUTH_WPA2_PSK;
    hotspot.ap.pmf_cfg.capable = true;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &hotspot));
    for (size_t i = 0; i < settings.wifi_networks.size(); ++i)
        if (settings.wifi_networks[i].ssid == settings.ssid) next_index = int(i);
    setup_ap = settings.wifi_networks.empty();
    ESP_ERROR_CHECK(esp_wifi_set_mode(setup_ap ? WIFI_MODE_APSTA : WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start()); offline_since = milliseconds();
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, const_cast<char *>("pool.ntp.org")); esp_sntp_init();
}
bool wifi_scan_request(std::string &error) {
    xSemaphoreTake(scan_mutex, portMAX_DELAY);
    bool ok = !scan_pending && milliseconds() - last_scan >= 15000;
    if (ok) { scan_pending = true; last_scan = milliseconds(); seen.clear(); scan_error.clear(); }
    else error = scan_pending ? "WLAN search is already running" : "Wait 15 seconds between WLAN searches";
    xSemaphoreGive(scan_mutex); return ok;
}
cJSON *wifi_scan_status() {
    xSemaphoreTake(scan_mutex, portMAX_DELAY);
    cJSON *json = cJSON_CreateObject();
    cJSON_AddBoolToObject(json, "busy", scan_pending);
    cJSON_AddStringToObject(json, "error", scan_error.c_str());
    cJSON *rows = cJSON_AddArrayToObject(json, "networks");
    for (const auto &ap : seen) {
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "ssid", ap.ssid.c_str());
        cJSON_AddNumberToObject(row, "rssi", ap.rssi);
        cJSON_AddStringToObject(row, "security", ap.security.c_str());
        cJSON_AddBoolToObject(row, "supported", ap.supported); cJSON_AddItemToArray(rows, row);
    }
    xSemaphoreGive(scan_mutex); return json;
}
static void finish_scan(const char *error) {
    xSemaphoreTake(scan_mutex, portMAX_DELAY);
    scan_error = error; scan_pending = false;
    xSemaphoreGive(scan_mutex);
    scanning = preparing_scan = false; attempt_until = 0;
}
static void collect_scan() {
    constexpr uint16_t limit = 32;
    auto records = std::unique_ptr<wifi_ap_record_t[]>(new (std::nothrow) wifi_ap_record_t[limit]);
    if (!records) { esp_wifi_clear_ap_list(); finish_scan("Not enough memory for WLAN search"); return; }
    uint16_t count = limit;
    if (esp_wifi_scan_get_ap_records(&count, records.get()) != ESP_OK) {
        esp_wifi_clear_ap_list(); finish_scan("WLAN search failed; please retry"); return;
    }
    xSemaphoreTake(scan_mutex, portMAX_DELAY);
    for (uint16_t i = 0; i < count; ++i) {
        const auto &ap = records[i];
        std::string ssid(reinterpret_cast<const char *>(ap.ssid), strnlen(reinterpret_cast<const char *>(ap.ssid), 32));
        // The portal and stored profiles support printable UTF-8 SSIDs.
        if (!valid_ssid(ssid)) continue;
        auto found = std::find_if(seen.begin(), seen.end(), [&](const Seen &p) { return p.ssid == ssid; });
        bool supported = ap.authmode == WIFI_AUTH_OPEN || ap.authmode == WIFI_AUTH_WPA_PSK ||
            ap.authmode == WIFI_AUTH_WPA2_PSK || ap.authmode == WIFI_AUTH_WPA_WPA2_PSK ||
            ap.authmode == WIFI_AUTH_WPA3_PSK || ap.authmode == WIFI_AUTH_WPA2_WPA3_PSK;
        const char *security = ap.authmode == WIFI_AUTH_OPEN ? "Offen" : supported ? "WPA/WPA2/WPA3" : "Nicht unterstützt";
        if (found == seen.end()) seen.push_back({ssid, security, ap.rssi, supported});
        else if (ap.rssi > found->rssi) *found = {ssid, security, ap.rssi, supported};
    }
    std::sort(seen.begin(), seen.end(), [](const Seen &a, const Seen &b) { return a.rssi > b.rssi; });
    xSemaphoreGive(scan_mutex); finish_scan("");
}
void wifi_tick(int64_t now) {
    if (online) {
        offline_since = now; was_online = true;
        if (setup_ap) { ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); setup_ap = false; }
    } else {
        if (was_online) { next_index = active.load(); attempt_until = 0; was_online = false; }
        if (!setup_ap && now - offline_since >= 30000) {
            ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA)); setup_ap = true;
        }
    }
    xSemaphoreTake(scan_mutex, portMAX_DELAY); bool pending = scan_pending; xSemaphoreGive(scan_mutex);
    if (pending) {
        if (!scanning && !preparing_scan) {
            // An offline connect attempt prevents IDF scans. Stop it first;
            // background scans on a connected station keep the existing link.
            preparing_scan = true; resume_at = now + 500;
            if (!online) esp_wifi_disconnect();
        }
        if (preparing_scan && now >= resume_at) {
            scan_done = false;
            wifi_scan_config_t config{}; config.show_hidden = false;
            config.scan_time.active.min = 30; config.scan_time.active.max = 120;
            if (esp_wifi_scan_start(&config, false) != ESP_OK) finish_scan("WLAN search could not start; please retry");
            else { preparing_scan = false; scanning = true; scan_started = now; }
        }
        if (scanning && scan_done.exchange(false)) {
            if (scan_failed) { esp_wifi_clear_ap_list(); finish_scan("WLAN search failed; please retry"); }
            else collect_scan();
        }
        else if (scanning && now - scan_started >= 15000) {
            esp_wifi_scan_stop(); esp_wifi_clear_ap_list(); finish_scan("WLAN search timed out");
        }
        return;
    }
    if (online || settings.wifi_networks.empty() || now < attempt_until) return;
    if (active >= 0) {
        // Give the disconnect event time to finish before switching profiles.
        esp_wifi_disconnect(); active = -1; resume_at = now + 500; return;
    }
    if (now < resume_at) return;
    const auto &profile = settings.wifi_networks[next_index];
    wifi_config_t config{};
    std::memcpy(config.sta.ssid, profile.ssid.data(), profile.ssid.size());
    std::memcpy(config.sta.password, profile.password.data(), profile.password.size());
    config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN; config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    config.sta.pmf_cfg.capable = true;
    config.sta.threshold.authmode = profile.password.empty() ? WIFI_AUTH_OPEN : WIFI_AUTH_WPA_PSK;
    config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    // Do not carry a custom resolver from a different WLAN into DHCP mode.
    // esp_netif_set_dns_info rejects zero addresses. Clear the global lwIP
    // slots in their owning TCP/IP task instead (the pinned SDK's default).
    ESP_ERROR_CHECK(esp_netif_tcpip_exec([](void *) -> esp_err_t {
        for (int slot = 0; slot < DNS_MAX_SERVERS; ++slot) dns_setserver(slot, nullptr);
        return ESP_OK;
    }, nullptr));
    active = next_index; next_index = (next_index + 1) % int(settings.wifi_networks.size());
    attempt_until = now + 15000; esp_wifi_connect();
}
void wifi_status(cJSON *json) {
    wifi_ap_record_t ap{};
    if (online && esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        std::string ssid(reinterpret_cast<const char *>(ap.ssid), strnlen(reinterpret_cast<const char *>(ap.ssid), 32));
        cJSON_AddStringToObject(json, "activeSsid", ssid.c_str());
        cJSON_AddNumberToObject(json, "rssi", ap.rssi);
    }
    cJSON_AddNumberToObject(json, "uptimeSeconds", milliseconds() / 1000);
}
}
