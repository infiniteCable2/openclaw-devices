#pragma once
// Narrow SDK model for compiling the real Wi-Fi manager on the host.
#include "nvs.h"
#include <cstddef>
#include <cstdint>
constexpr int ESP_ERR_NO_MEM = 5, WIFI_STORAGE_RAM = 0;
using esp_event_base_t = const char *;
inline constexpr char WIFI_EVENT[] = "wifi", IP_EVENT[] = "ip";
constexpr int ESP_EVENT_ANY_ID = -1, IP_EVENT_STA_GOT_IP = 1;
constexpr int WIFI_EVENT_STA_DISCONNECTED = 2, WIFI_EVENT_SCAN_DONE = 3;
using event_handler = void (*)(void *, esp_event_base_t, int32_t, void *);
esp_err_t esp_event_loop_create_default();
esp_err_t esp_event_handler_register(esp_event_base_t, int32_t, event_handler, void *);
struct esp_netif_t {};
enum esp_netif_dns_type_t { ESP_NETIF_DNS_MAIN, ESP_NETIF_DNS_BACKUP, ESP_NETIF_DNS_FALLBACK, ESP_NETIF_DNS_MAX };
constexpr int ESP_IPADDR_TYPE_V4 = 0, DNS_MAX_SERVERS = 3;
struct esp_netif_dns_info_t { struct { int type; struct { struct { uint32_t addr; } ip4; } u_addr; } ip; };
esp_err_t esp_netif_init();
esp_netif_t *esp_netif_create_default_wifi_sta();
esp_netif_t *esp_netif_create_default_wifi_ap();
esp_err_t esp_netif_set_dns_info(esp_netif_t *, esp_netif_dns_type_t, esp_netif_dns_info_t *);
esp_err_t esp_netif_tcpip_exec(esp_err_t (*)(void *), void *);
void dns_setserver(int, const void *);
inline uint32_t htonl(uint32_t n) { return (n << 24) | ((n << 8) & 0xff0000U) | ((n >> 8) & 0xff00U) | (n >> 24); }
constexpr int SNTP_OPMODE_POLL = 0;
void esp_sntp_setoperatingmode(int);
void esp_sntp_setservername(int, char *);
void esp_sntp_init();
int64_t esp_timer_get_time();
using SemaphoreHandle_t = void *;
constexpr int portMAX_DELAY = -1;
SemaphoreHandle_t xSemaphoreCreateMutex();
void xSemaphoreTake(SemaphoreHandle_t, int);
void xSemaphoreGive(SemaphoreHandle_t);
enum wifi_mode_t { WIFI_MODE_STA, WIFI_MODE_APSTA };
enum wifi_auth_mode_t { WIFI_AUTH_OPEN, WIFI_AUTH_WEP, WIFI_AUTH_WPA_PSK, WIFI_AUTH_WPA2_PSK,
    WIFI_AUTH_WPA_WPA2_PSK, WIFI_AUTH_WPA2_ENTERPRISE, WIFI_AUTH_WPA3_PSK, WIFI_AUTH_WPA2_WPA3_PSK };
constexpr int WIFI_IF_STA = 0, WIFI_IF_AP = 1, WIFI_ALL_CHANNEL_SCAN = 1, WIFI_CONNECT_AP_BY_SIGNAL = 0, WPA3_SAE_PWE_BOTH = 2;
struct wifi_init_config_t {};
#define WIFI_INIT_CONFIG_DEFAULT() wifi_init_config_t{}
struct wifi_config_t {
    struct { uint8_t ssid[32], password[64]; int scan_method, sort_method, sae_pwe_h2e;
        struct { bool capable; } pmf_cfg; struct { wifi_auth_mode_t authmode; } threshold; } sta;
    struct { uint8_t ssid[32], password[64]; size_t ssid_len; int channel, max_connection;
        wifi_auth_mode_t authmode; struct { bool capable; } pmf_cfg; } ap;
};
struct wifi_ap_record_t { uint8_t ssid[33]; wifi_auth_mode_t authmode; int rssi; };
struct wifi_scan_config_t { bool show_hidden; struct { struct { int min, max; } active; } scan_time; };
struct wifi_event_sta_scan_done_t { uint32_t status; };
esp_err_t esp_wifi_init(wifi_init_config_t *);
esp_err_t esp_wifi_set_storage(int);
esp_err_t esp_wifi_set_mode(wifi_mode_t);
esp_err_t esp_wifi_set_config(int, wifi_config_t *);
esp_err_t esp_wifi_start();
esp_err_t esp_wifi_connect();
esp_err_t esp_wifi_disconnect();
esp_err_t esp_wifi_scan_start(wifi_scan_config_t *, bool);
esp_err_t esp_wifi_scan_stop();
esp_err_t esp_wifi_scan_get_ap_records(uint16_t *, wifi_ap_record_t *);
esp_err_t esp_wifi_clear_ap_list();
esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *);
