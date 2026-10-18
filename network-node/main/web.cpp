#include "settings.hpp"
#include "portal.hpp"
#include <algorithm>
#include <cstring>
#include <memory>
#include <ctime>
#include <sys/time.h>
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "lwip/inet.h"
#include "mbedtls/x509_crt.h"
#include "sodium.h"

namespace netnode {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
static std::string csrf;
static unsigned failures = 0;
static int64_t blocked_until = 0;
static std::string header(httpd_req_t *req, const char *name, size_t maximum) {
    size_t length = httpd_req_get_hdr_value_len(req, name);
    if (!length || length > maximum) return "";
    std::vector<char> value(length + 1);
    if (httpd_req_get_hdr_value_str(req, name, value.data(), value.size()) != ESP_OK) return "";
    return value.data();
}
static void headers(httpd_req_t *req) {
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(req, "X-Frame-Options", "DENY");
    httpd_resp_set_hdr(req, "Referrer-Policy", "no-referrer");
    httpd_resp_set_hdr(req, "Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'");
}
static esp_err_t message(httpd_req_t *req, const char *status, const char *text) {
    headers(req); httpd_resp_set_status(req, status); httpd_resp_set_type(req, "text/plain; charset=utf-8");
    return httpd_resp_sendstr(req, text);
}
static bool authenticated(httpd_req_t *req) {
    int64_t now = esp_timer_get_time() / 1000;
    if (now < blocked_until) { message(req, "429 Too Many Requests", "Try again shortly"); return false; }
    std::string authorization = header(req, "Authorization", 256);
    uint8_t raw[128]{}; size_t size = 0;
    bool valid = authorization.compare(0, 6, "Basic ") == 0 &&
        sodium_base642bin(raw, sizeof(raw) - 1, authorization.data() + 6, authorization.size() - 6,
            nullptr, &size, nullptr, sodium_base64_VARIANT_ORIGINAL) == 0;
    std::string decoded(reinterpret_cast<char *>(raw), size);
    valid = valid && decoded.compare(0, 6, "admin:") == 0 && verify_password(decoded.substr(6));
    sodium_memzero(raw, sizeof(raw));
    if (valid) { failures = 0; return true; }
    if (!authorization.empty() && ++failures >= 5) { blocked_until = now + 3000; failures = 0; }
    httpd_resp_set_hdr(req, "WWW-Authenticate", "Basic realm=\"OpenClaw Network Node\", charset=\"UTF-8\"");
    message(req, "401 Unauthorized", "Sign in as admin"); return false;
}
static bool mutation_allowed(httpd_req_t *req) {
    if (!authenticated(req)) return false;
    std::string origin = header(req, "Origin", 256);
    std::string host = header(req, "Host", 128);
    if (header(req, "X-CSRF-Token", 64) != csrf || (!origin.empty() && origin != "http://" + host) ||
        header(req, "Content-Type", 64) != "application/json" || stopping) {
        message(req, "403 Forbidden", "Reload the setup page and try again"); return false;
    }
    return true;
}
static Json body(httpd_req_t *req) {
    if (req->content_len <= 0 || req->content_len > max_body) return Json(nullptr, cJSON_Delete);
    std::vector<char> buffer(req->content_len + 1, 0);
    size_t cursor = 0;
    while (cursor < req->content_len) {
        int size = httpd_req_recv(req, buffer.data() + cursor, req->content_len - cursor);
        if (size <= 0) return Json(nullptr, cJSON_Delete);
        cursor += size;
    }
    return Json(cJSON_ParseWithLength(buffer.data(), buffer.size()), cJSON_Delete);
}
static esp_err_t portal(httpd_req_t *req) {
    if (!authenticated(req)) return ESP_OK;
    headers(req); httpd_resp_set_type(req, "text/html; charset=utf-8");
    return httpd_resp_send(req, portal_html, sizeof(portal_html) - 1);
}
static esp_err_t status(httpd_req_t *req) {
    if (!authenticated(req)) return ESP_OK;
    Json json(settings_json(settings, false), cJSON_Delete);
    cJSON_AddStringToObject(json.get(), "csrf", csrf.c_str());
    cJSON_AddBoolToObject(json.get(), "online", online);
    cJSON_AddBoolToObject(json.get(), "gatewayReady", gateway_ready);
    cJSON_AddBoolToObject(json.get(), "authBlocked", auth_blocked);
    cJSON_AddBoolToObject(json.get(), "setupAp", setup_ap);
    cJSON_AddBoolToObject(json.get(), "clockReady", std::time(nullptr) >= 1704067200);
    cJSON_AddBoolToObject(json.get(), "enrollmentPending", !enrollment_code().empty());
    esp_netif_ip_info_t info{};
    auto *iface = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_dns_info_t dns{};
    if (iface && esp_netif_get_dns_info(iface, ESP_NETIF_DNS_MAIN, &dns) == ESP_OK &&
        dns.ip.type == ESP_IPADDR_TYPE_V4)
        cJSON_AddStringToObject(json.get(), "activeDns", ip_text(ntohl(dns.ip.u_addr.ip4.addr)).c_str());
    if (iface && esp_netif_get_ip_info(iface, &info) == ESP_OK)
        cJSON_AddStringToObject(json.get(), "ip", ip_text(ntohl(info.ip.addr)).c_str());
    char *raw = cJSON_PrintUnformatted(json.get());
    if (!raw) return message(req, "503 Service Unavailable", "Not enough memory");
    headers(req); httpd_resp_set_type(req, "application/json");
    esp_err_t result = httpd_resp_sendstr(req, raw); free(raw); return result;
}
static bool validate_setup_code(const std::string &code, const std::string &gateway) {
    if (code.empty()) return true;
    std::vector<unsigned char> decoded(2049, 0); size_t length = 0;
    if (sodium_base642bin(decoded.data(), decoded.size() - 1, code.data(), code.size(), nullptr,
        &length, nullptr, sodium_base64_VARIANT_URLSAFE_NO_PADDING)) return false;
    Json json(cJSON_ParseWithLength(reinterpret_cast<char *>(decoded.data()), length), cJSON_Delete);
    std::string url;
    if (!string_field(json.get(), "url", 256, url) || !wss_url(url) || url != gateway) return false;
    int secrets = 0;
    for (const char *name : {"bootstrapToken", "token", "password"}) {
        auto value = cJSON_GetObjectItemCaseSensitive(json.get(), name);
        if (value) {
            std::string secret;
            if (!string_field(json.get(), name, 1024, secret) || secret.empty()) return false;
            ++secrets;
        }
    }
    return secrets == 1;
}
static esp_err_t save(httpd_req_t *req) {
    if (!mutation_allowed(req)) return ESP_OK;
    Json json = body(req);
    if (!json) return message(req, "400 Bad Request", "Invalid or oversized JSON");
    Settings next;
    std::string error, setup_code;
    if (!parse_settings(json.get(), settings, next, error)) return message(req, "400 Bad Request", error.c_str());
    if (!string_field(json.get(), "setupCode", 2048, setup_code) || !validate_setup_code(setup_code, next.gateway))
        return message(req, "400 Bad Request", "Setup code must contain this exact wss:// Gateway URL and one credential");
    if (!next.ca.empty()) {
        mbedtls_x509_crt ca; mbedtls_x509_crt_init(&ca);
        int valid = mbedtls_x509_crt_parse(&ca, reinterpret_cast<const unsigned char *>(next.ca.c_str()), next.ca.size() + 1);
        mbedtls_x509_crt_free(&ca);
        if (valid != 0) return message(req, "400 Bad Request", "Invalid CA certificate");
    }
    if (!settings_save(next, setup_code)) return message(req, "503 Service Unavailable", "Settings could not be saved");
    message(req, "200 OK", "Saved. Restarting; reconnect using the device's LAN address or setup hotspot.");
    schedule_restart(false); return ESP_OK;
}
static esp_err_t password(httpd_req_t *req) {
    if (!mutation_allowed(req)) return ESP_OK;
    Json json = body(req);
    std::string current, next;
    if (!string_field(json.get(), "current", 72, current) || !verify_password(current) ||
        !string_field(json.get(), "password", 72, next) || !change_password(next))
        return message(req, "400 Bad Request", "Check current password; new password needs 10-72 printable ASCII characters");
    csrf = random_hex(16);
    return message(req, "200 OK", "Password changed. Reload and sign in with the new password. Hotspot password is unchanged.");
}
static esp_err_t reset(httpd_req_t *req) {
    if (!mutation_allowed(req)) return ESP_OK;
    Json json = body(req);
    std::string confirmation, current;
    if (!string_field(json.get(), "confirmation", 16, confirmation) || confirmation != "RESET" ||
        !string_field(json.get(), "password", 72, current) || !verify_password(current))
        return message(req, "400 Bad Request", "Enter RESET and the current password");
    message(req, "200 OK", "Factory reset scheduled. Wi-Fi, rules and device identity will be erased. Sticker credentials stay; the web password returns to the sticker password.");
    schedule_restart(true); return ESP_OK;
}
static esp_err_t clock_set(httpd_req_t *req) {
    if (!mutation_allowed(req)) return ESP_OK;
    Json json = body(req);
    int seconds;
    if (!integer(json.get(), "seconds", 1704067200, 2145916800, seconds))
        return message(req, "400 Bad Request", "Invalid device time");
    timeval clock{seconds, 0};
    if (settimeofday(&clock, nullptr)) return message(req, "503 Service Unavailable", "Clock could not be set");
    return message(req, "200 OK", "Device clock set from browser. OpenClaw can now validate certificate dates.");
}
void web_start() {
    csrf = random_hex(16);
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 12288; config.max_uri_handlers = 6; config.max_open_sockets = 3;
    config.lru_purge_enable = true; config.recv_wait_timeout = 3; config.send_wait_timeout = 3;
    httpd_handle_t server = nullptr; ESP_ERROR_CHECK(httpd_start(&server, &config));
    struct Route { const char *uri; httpd_method_t method; esp_err_t (*handler)(httpd_req_t *); };
    for (auto route : {Route{"/", HTTP_GET, portal}, {"/api/status", HTTP_GET, status},
        {"/api/settings", HTTP_POST, save}, {"/api/password", HTTP_POST, password}, {"/api/reset", HTTP_POST, reset}, {"/api/time", HTTP_POST, clock_set}}) {
        httpd_uri_t uri{}; uri.uri = route.uri; uri.method = route.method; uri.handler = route.handler;
        ESP_ERROR_CHECK(httpd_register_uri_handler(server, &uri));
    }
}
}
