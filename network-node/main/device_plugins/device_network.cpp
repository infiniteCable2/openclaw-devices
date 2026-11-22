#include "device_network.hpp"
#include "core.hpp"
#include "esp_http_client.h"
#include "esp_timer.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "mdns.h"
#include <algorithm>
#include <memory>
#include <type_traits>

namespace netnode {
DeviceNetworkError visit_local_services(const ManagedDeviceLink &link, const char *service, const char *protocol,
                                       uint32_t timeout_ms, ServiceVisitor visit, void *context) {
    constexpr size_t max_txt_fields = 32, max_results = 12;
    mdns_result_t *raw = nullptr;
    auto status = mdns_query_ptr(service, protocol, timeout_ms, max_results, &raw);
    std::unique_ptr<mdns_result_t, decltype(&mdns_query_results_free)> results(raw, mdns_query_results_free);
    if (!link.current()) return DeviceNetworkError::wifi_changed;
    if (status != ESP_OK && status != ESP_ERR_NOT_FOUND) return DeviceNetworkError::unavailable;
    for (auto *row = results.get(); row; row = row->next) {
        if (row->esp_netif != link.interface || row->txt_count > max_txt_fields ||
            (row->txt_count && (!row->txt || !row->txt_value_len))) continue;
        DnsSdService info{row->instance_name ? row->instance_name : "", row->port, {}, {}};
        info.txt.reserve(row->txt_count);
        for (size_t i = 0; i < row->txt_count; ++i) {
            const auto &entry = row->txt[i];
            if (!entry.key) continue;
            info.txt.push_back({entry.key, entry.value ? std::string_view(entry.value, row->txt_value_len[i])
                                                      : std::string_view{}, entry.value != nullptr});
        }
        for (auto *entry = row->addr; entry; entry = entry->next) {
            if (entry->addr.type != ESP_IPADDR_TYPE_V4) continue;
            uint32_t address = ntohl(entry->addr.u_addr.ip4.addr);
            if (link.contains(address)) info.addresses.push_back(address);
        }
        if (!visit(info, context)) break;
    }
    return DeviceNetworkError::none;
}

DeviceHttpResponse read_local_json(const ManagedDeviceLink &link, uint32_t address, uint16_t port, const char *path,
                                  size_t max_bytes, int64_t deadline) {
    using Http = std::unique_ptr<std::remove_pointer_t<esp_http_client_handle_t>, decltype(&esp_http_client_cleanup)>;
    constexpr DeviceNetworkError changed = DeviceNetworkError::wifi_changed;
    constexpr DeviceNetworkError timeout = DeviceNetworkError::timeout;
    constexpr DeviceNetworkError unavailable = DeviceNetworkError::unavailable;
    constexpr DeviceNetworkError too_large = DeviceNetworkError::response_too_large;
    if (!link.current() || !link.contains(address)) return {{}, changed};
    struct ifreq interface{};
    if (esp_netif_get_netif_impl_name(link.interface, interface.ifr_name) != ESP_OK) return {{}, unavailable};
    std::string url = "http://" + ip_text(address) + ":" + std::to_string(port) + path;
    auto remaining_ms = [deadline]() -> int {
        return static_cast<int>(std::min<int64_t>(1300, (deadline - esp_timer_get_time()) / 1000));
    };
    int first_timeout = remaining_ms();
    if (first_timeout <= 0) return {{}, timeout};
    esp_http_client_config_t config{};
    config.url = url.c_str();
    config.method = HTTP_METHOD_GET;
    config.timeout_ms = first_timeout;
    config.disable_auto_redirect = true;
    config.max_authorization_retries = -1;
    config.if_name = &interface;
    Http client(esp_http_client_init(&config), esp_http_client_cleanup);
    if (!client || esp_http_client_set_header(client.get(), "Accept", "application/json") != ESP_OK)
        return {{}, unavailable};
    if (esp_http_client_open(client.get(), 0) != ESP_OK) return {{}, remaining_ms() <= 0 ? timeout : unavailable};
    auto update_timeout = [&]() {
        int available = remaining_ms();
        return available > 0 && esp_http_client_set_timeout_ms(client.get(), available) == ESP_OK;
    };
    if (!update_timeout()) return {{}, timeout};
    int64_t length = esp_http_client_fetch_headers(client.get());
    if (length == -ESP_ERR_HTTP_EAGAIN || remaining_ms() <= 0) return {{}, timeout};
    if (length < 0) return {{}, unavailable};
    int status = esp_http_client_get_status_code(client.get());
    if (status < 200 || status >= 300) return {{}, DeviceNetworkError::rejected};
    if (length > static_cast<int64_t>(max_bytes)) return {{}, too_large};

    DeviceHttpResponse result;
    result.body.reserve(static_cast<size_t>(length));
    char buffer[512];
    for (;;) {
        if (!link.current()) return {{}, changed};
        if (!update_timeout()) return {{}, timeout};
        int received = esp_http_client_read(client.get(), buffer, sizeof(buffer));
        if (received == -ESP_ERR_HTTP_EAGAIN || remaining_ms() <= 0) return {{}, timeout};
        if (received < 0) return {{}, unavailable};
        if (received == 0) {
            if (!esp_http_client_is_complete_data_received(client.get())) return {{}, unavailable};
            return result;
        }
        auto bytes = static_cast<size_t>(received);
        if (bytes > max_bytes - result.body.size()) return {{}, too_large};
        result.body.append(buffer, bytes);
    }
}
}
