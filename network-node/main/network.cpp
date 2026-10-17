#include "settings.hpp"
#include "network.hpp"
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include "esp_random.h"
#include "esp_netif.h"
#include "esp_netif_net_stack.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/etharp.h"
#include "lwip/inet_chksum.h"
#include "lwip/prot/icmp.h"
#include "lwip/sockets.h"
#include "lwip/tcpip.h"
#include "sodium.h"

namespace netnode {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
static SemaphoreHandle_t mutex;
static uint32_t epoch = 1;
static int64_t now() { return esp_timer_get_time() / 1000; }
struct Lock { Lock() { xSemaphoreTake(mutex, portMAX_DELAY); } ~Lock() { xSemaphoreGive(mutex); } };
struct Stream {
    int fd = -1;
    std::string id, owner;
    uint32_t address = 0;
    uint16_t port = 0;
    Protocol protocol = Protocol::tcp;
    bool connecting = false, write_closed = false;
    int64_t created = 0, touched = 0;
    void close() { if (fd >= 0) ::close(fd); fd = -1; id.clear(); owner.clear(); }
};
static Stream streams[max_streams];
struct Target { uint32_t address; uint16_t port; };
struct Probe {
    std::string id, owner;
    std::vector<Target> targets;
    bool ping = false;
    std::atomic<bool> cancel{false};
    bool done = false;
    bool complete = false;
    uint32_t generation;
    int64_t created;
    std::string result;
};
static Probe *probe = nullptr;
struct MacLookup { uint32_t address; SemaphoreHandle_t done; bool found = false; uint8_t mac[6]{}; };
static void lookup_mac(void *data) {
    auto *request = static_cast<MacLookup *>(data);
    auto *iface = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    auto *netif = iface ? static_cast<struct netif *>(esp_netif_get_netif_impl(iface)) : nullptr;
    ip4_addr_t address{htonl(request->address)};
    if (netif && ip4_addr_netcmp(&address, netif_ip4_addr(netif), netif_ip4_netmask(netif))) {
        struct eth_addr *mac = nullptr;
        const ip4_addr_t *entry = nullptr;
        if (etharp_find_addr(netif, &address, &mac, &entry) >= 0) {
            std::memcpy(request->mac, mac->addr, 6); request->found = true;
        } else etharp_request(netif, &address); // ARP only; no IP payload before a pin matches.
    }
    xSemaphoreGive(request->done);
}
static bool permitted(uint32_t address, Protocol protocol, uint16_t port) {
    if (stopping || !online || !gateway_ready) return false;
    // Never turn the transport into an alternate management interface.
    if ((address & 0xffffff00U) == 0xc0a80400U) return false;
    esp_netif_ip_info_t info{};
    auto *iface = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (iface && esp_netif_get_ip_info(iface, &info) == ESP_OK && address == ntohl(info.ip.addr)) return false;
    if (allows(settings, address, protocol, port)) return true;
    if (!needs_mac(settings, address, protocol, port)) return false;
    MacLookup lookup{}; lookup.address = address;
    lookup.done = xSemaphoreCreateBinary();
    if (!lookup.done) return false;
    bool queued = tcpip_callback(lookup_mac, &lookup) == ERR_OK;
    if (queued) xSemaphoreTake(lookup.done, portMAX_DELAY);
    vSemaphoreDelete(lookup.done);
    if (!queued || !lookup.found) return false;
    char mac[18];
    std::snprintf(mac, sizeof(mac), "%02x:%02x:%02x:%02x:%02x:%02x", lookup.mac[0], lookup.mac[1],
                  lookup.mac[2], lookup.mac[3], lookup.mac[4], lookup.mac[5]);
    return allows(settings, address, protocol, port, mac);
}
static cJSON *reply(const char *state) {
    cJSON *json = cJSON_CreateObject(); cJSON_AddStringToObject(json, "state", state); return json;
}
static cJSON *failure(const char *code) {
    cJSON *json = reply("error"); cJSON_AddStringToObject(json, "code", code); return json;
}
static bool parse_target(const cJSON *params, uint32_t &address, uint16_t &port, Protocol protocol) {
    std::string host; int number = 0;
    if (!string_field(params, "host", 15, host) || !ipv4(host, address)) return false;
    if (protocol != Protocol::icmp && !integer(params, "port", 1, 65535, number)) return false;
    port = number;
    return true;
}
static sockaddr_in endpoint(uint32_t address, uint16_t port) {
    sockaddr_in out{}; out.sin_family = AF_INET; out.sin_addr.s_addr = htonl(address); out.sin_port = htons(port); return out;
}
static int connect_socket(uint32_t address, uint16_t port, Protocol protocol, bool &connecting) {
    int fd = ::socket(AF_INET, protocol == Protocol::udp ? SOCK_DGRAM : SOCK_STREAM, 0);
    if (fd < 0) return -1;
    if (fcntl(fd, F_SETFL, O_NONBLOCK) != 0) { ::close(fd); return -1; }
    if (protocol == Protocol::udp) { int yes = 1; setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &yes, sizeof(yes)); }
    auto target = endpoint(address, port);
    int status = ::connect(fd, reinterpret_cast<sockaddr *>(&target), sizeof(target));
    connecting = status < 0 && errno == EINPROGRESS;
    if (status < 0 && !connecting) { ::close(fd); return -1; }
    return fd;
}
static bool connection_ready(Stream &stream) {
    if (!stream.connecting) return true;
    fd_set writes; FD_ZERO(&writes); FD_SET(stream.fd, &writes);
    timeval timeout{};
    int status = ::select(stream.fd + 1, nullptr, &writes, nullptr, &timeout);
    if (status == 0) return false;
    int error = 0; socklen_t length = sizeof(error);
    if (status < 0 || getsockopt(stream.fd, SOL_SOCKET, SO_ERROR, &error, &length) || error) {
        stream.close(); return false;
    }
    stream.connecting = false; return true;
}
static std::string encode(const uint8_t *data, size_t size) {
    std::string out(sodium_base64_ENCODED_LEN(size, sodium_base64_VARIANT_ORIGINAL), '\0');
    sodium_bin2base64(out.data(), out.size(), data, size, sodium_base64_VARIANT_ORIGINAL);
    out.resize(std::strlen(out.c_str())); return out;
}
static cJSON *transport(const cJSON *params, const std::string &owner) {
    std::string op;
    if (!string_field(params, "op", 16, op)) return failure("invalid_request");
    Lock guard;
    if (op == "open") {
        std::string kind;
        if (!string_field(params, "protocol", 3, kind) || (kind != "tcp" && kind != "udp")) return failure("invalid_protocol");
        Protocol protocol = kind == "tcp" ? Protocol::tcp : Protocol::udp;
        uint32_t address; uint16_t port;
        if (!parse_target(params, address, port, protocol)) return failure("invalid_target");
        if (!permitted(address, protocol, port)) return failure("target_denied");
        Stream *free = nullptr;
        for (auto &stream : streams) if (stream.fd < 0) { free = &stream; break; }
        if (!free) return failure("capacity");
        free->fd = connect_socket(address, port, protocol, free->connecting);
        if (free->fd < 0) return failure("connect_failed");
        free->address = address; free->port = port; free->protocol = protocol;
        free->id = random_hex(16); free->owner = owner; free->created = free->touched = now(); free->write_closed = false;
        cJSON *json = reply(free->connecting ? "connecting" : "open");
        cJSON_AddStringToObject(json, "id", free->id.c_str()); return json;
    }
    std::string id;
    if (!string_field(params, "id", 32, id) || id.size() != 32) return failure("invalid_handle");
    Stream *selected = nullptr;
    for (auto &stream : streams) if (stream.fd >= 0 && stream.id == id && stream.owner == owner) selected = &stream;
    if (!selected) return failure("unknown_handle");
    auto &stream = *selected;
    if (op == "close") { stream.close(); return reply("closed"); }
    if (now() - stream.touched > 15000 || now() - stream.created > 300000 ||
        !permitted(stream.address, stream.protocol, stream.port)) { stream.close(); return failure("expired_or_denied"); }
    stream.touched = now();
    if (!connection_ready(stream)) return stream.fd < 0 ? failure("connect_failed") : reply("connecting");
    if (op == "poll") return reply("open");
    if (op == "shutdown") {
        if (stream.protocol != Protocol::tcp) return failure("invalid_operation");
        if (!stream.write_closed && ::shutdown(stream.fd, SHUT_WR)) return failure("socket_error");
        stream.write_closed = true; return reply("open");
    }
    if (op == "write") {
        std::string encoded;
        if (stream.write_closed || !string_field(params, "data", 2732, encoded)) return failure("invalid_data");
        uint8_t data[max_chunk]; size_t length = 0;
        if (sodium_base642bin(data, sizeof(data), encoded.data(), encoded.size(), nullptr, &length, nullptr,
            sodium_base64_VARIANT_ORIGINAL) != 0 || !length ||
            (stream.protocol == Protocol::udp && length > max_datagram)) return failure("invalid_data");
        int count = ::send(stream.fd, data, length, 0);
        if (count < 0 && errno != EWOULDBLOCK && errno != EAGAIN) { stream.close(); return failure("socket_error"); }
        cJSON *json = reply("open"); cJSON_AddNumberToObject(json, "written", std::max(count, 0)); return json;
    }
    if (op == "read") {
        uint8_t data[max_chunk];
        int count = ::recv(stream.fd, data, stream.protocol == Protocol::udp ? max_datagram + 1 : max_chunk, 0);
        if (stream.protocol == Protocol::udp && count > int(max_datagram)) return failure("datagram_too_large");
        if (count < 0 && errno != EWOULDBLOCK && errno != EAGAIN) { stream.close(); return failure("socket_error"); }
        cJSON *json = reply(count == 0 && stream.protocol == Protocol::tcp ? "eof" : "open");
        if (count >= 0) cJSON_AddStringToObject(json, "data", encode(data, count).c_str());
        return json;
    }
    return failure("invalid_operation");
}
static bool probe_allowed(Probe *job, const Target &target) {
    Lock guard;
    return !job->cancel && epoch == job->generation && !stopping && gateway_ready &&
        (job->ping ? settings.ping : settings.scan) &&
        permitted(target.address, job->ping ? Protocol::icmp : Protocol::tcp, target.port);
}
static bool ping_once(Probe *job, const Target &target) {
    int fd = ::socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
    if (fd < 0) return false;
    fcntl(fd, F_SETFL, O_NONBLOCK);
    struct Packet { icmp_echo_hdr header; uint8_t nonce[8]; } packet{};
    ICMPH_TYPE_SET(&packet.header, ICMP_ECHO);
    packet.header.id = htons(uint16_t(esp_random())); packet.header.seqno = htons(1);
    esp_fill_random(packet.nonce, sizeof(packet.nonce));
    packet.header.chksum = inet_chksum(&packet, sizeof(packet));
    auto address = endpoint(target.address, 0);
    // Recheck just before emission; the worker never reuses a previous connection's grant.
    bool sent = false;
    { Lock guard;
      if (!job->cancel && epoch == job->generation && settings.ping && permitted(target.address, Protocol::icmp, 0))
          sent = ::sendto(fd, &packet, sizeof(packet), 0, reinterpret_cast<sockaddr *>(&address), sizeof(address)) == static_cast<int>(sizeof(packet));
    }
    bool answered = false;
    int64_t end = now() + 200;
    while (sent && now() < end && probe_allowed(job, target)) {
        uint8_t buffer[128]; sockaddr_in peer{}; socklen_t size = sizeof(peer);
        int count = recvfrom(fd, buffer, sizeof(buffer), 0, reinterpret_cast<sockaddr *>(&peer), &size);
        if (count >= 20 + int(sizeof(packet)) && peer.sin_addr.s_addr == address.sin_addr.s_addr) {
            size_t header = (buffer[0] & 15U) * 4U;
            if (header >= 20 && header + sizeof(packet) <= size_t(count)) {
                Packet response{}; std::memcpy(&response, buffer + header, sizeof(response));
                if (ICMPH_TYPE(&response.header) == ICMP_ER && response.header.code == 0 &&
                    response.header.id == packet.header.id && response.header.seqno == packet.header.seqno &&
                    !std::memcmp(response.nonce, packet.nonce, sizeof(packet.nonce))) { answered = true; break; }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ::close(fd); return answered;
}
static void probe_worker(void *context) {
    auto *job = static_cast<Probe *>(context);
    Json results(cJSON_CreateArray(), cJSON_Delete);
    for (const auto &target : job->targets) {
        if (now() - job->created > 7000 || !probe_allowed(job, target)) break;
        int64_t started = now();
        bool open = false;
        if (job->ping) open = ping_once(job, target);
        else {
            bool connecting = false;
            // Keep check + connect in the same authority lock as invalidation.
            int fd = -1;
            { Lock guard; if (!job->cancel && epoch == job->generation && permitted(target.address, Protocol::tcp, target.port))
                fd = connect_socket(target.address, target.port, Protocol::tcp, connecting); }
            if (fd >= 0) {
                while (now() - started < 150 && probe_allowed(job, target)) {
                    fd_set writes; FD_ZERO(&writes); FD_SET(fd, &writes);
                    timeval timeout{0, 10000};
                    if (::select(fd + 1, nullptr, &writes, nullptr, &timeout) > 0) {
                        int error = 0; socklen_t length = sizeof(error);
                        open = getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) == 0 && error == 0; break;
                    }
                }
                ::close(fd);
            }
        }
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "host", ip_text(target.address).c_str());
        cJSON_AddNumberToObject(row, "port", target.port);
        cJSON_AddStringToObject(row, "observation", open ? (job->ping ? "echo_reply" : "tcp_open") : "no_confirmation");
        cJSON_AddNumberToObject(row, "elapsedMs", now() - started); cJSON_AddItemToArray(results.get(), row);
    }
    char *raw = cJSON_PrintUnformatted(results.get());
    { Lock guard;
      job->result = raw ? raw : "[]";
      job->complete = raw && cJSON_GetArraySize(results.get()) == int(job->targets.size()) && !job->cancel && job->generation == epoch;
      job->done = true;
    }
    free(raw);
    results.reset();
    // No access to job after publishing done: a following command may reclaim it.
    vTaskDelete(nullptr);
}
static cJSON *probe_command(const cJSON *params, const std::string &owner) {
    std::string op;
    if (!string_field(params, "op", 16, op)) return failure("invalid_request");
    Lock guard;
    if (op == "start") {
        std::string kind;
        if (!string_field(params, "kind", 8, kind) || (kind != "ping" && kind != "scan")) return failure("invalid_probe");
        if (probe && !probe->done) return failure("capacity");
        bool ping = kind == "ping";
        if (!(ping ? settings.ping : settings.scan)) return failure("probe_denied");
        auto targets = cJSON_GetObjectItemCaseSensitive(params, "targets");
        if (!cJSON_IsArray(targets) || cJSON_GetArraySize(targets) < 1 ||
            cJSON_GetArraySize(targets) > int(max_scan_targets)) return failure("invalid_targets");
        auto *job = new (std::nothrow) Probe();
        if (!job) return failure("capacity");
        job->id = random_hex(16); job->owner = owner; job->ping = ping; job->created = now(); job->generation = epoch;
        const cJSON *row;
        cJSON_ArrayForEach(row, targets) {
            Target target{};
            if (!parse_target(row, target.address, target.port, ping ? Protocol::icmp : Protocol::tcp) ||
                !permitted(target.address, ping ? Protocol::icmp : Protocol::tcp, target.port)) {
                delete job; return failure("target_denied");
            }
            job->targets.push_back(target);
        }
        delete probe; probe = job;
        cJSON *json = reply("running"); cJSON_AddStringToObject(json, "id", job->id.c_str());
        if (xTaskCreate(probe_worker, "network-probe", 6144, job, 3, nullptr) != pdPASS) {
            delete probe; probe = nullptr; cJSON_Delete(json); return failure("capacity");
        }
        return json;
    }
    std::string id;
    if (!string_field(params, "id", 32, id) || !probe || probe->id != id || probe->owner != owner) return failure("unknown_handle");
    if (op == "cancel") { probe->cancel = true; return reply("cancelling"); }
    if (op != "poll") return failure("invalid_operation");
    cJSON *json = reply(probe->done ? "done" : "running");
    cJSON_AddBoolToObject(json, "cancelled", probe->cancel);
    cJSON_AddBoolToObject(json, "complete", probe->complete);
    if (probe->done) cJSON_AddItemToObject(json, "results", cJSON_Parse(probe->result.c_str()));
    return json;
}
static esp_err_t command(esp_openclaw_node_handle_t, void *context,
    const esp_openclaw_node_command_invocation_t *invocation, const char *raw, size_t length,
    char **payload, esp_openclaw_node_error_t *error) {
    if (length > 6144 || stopping || !gateway_ready || !invocation || !invocation->session_key ||
        !*invocation->session_key) { error->code = "NOT_AUTHORIZED"; error->message = "A live session-bound invocation is required"; return ESP_ERR_INVALID_STATE; }
    Json params(cJSON_ParseWithLength(raw, length), cJSON_Delete);
    std::string context_id;
    if (!cJSON_IsObject(params.get()) || !string_field(params.get(), "context", 48, context_id) || context_id != settings.context) {
        error->code = "INVALID_CONTEXT"; error->message = "Select this node's configured network context"; return ESP_ERR_INVALID_ARG;
    }
    Json result(context ? probe_command(params.get(), invocation->session_key) : transport(params.get(), invocation->session_key), cJSON_Delete);
    *payload = cJSON_PrintUnformatted(result.get());
    return *payload ? ESP_OK : ESP_ERR_NO_MEM;
}
void network_invalidate() {
    Lock guard;
    ++epoch;
    for (auto &stream : streams) stream.close();
    if (probe) probe->cancel = true;
}
static void janitor(void *) {
    for (;;) {
        { Lock guard;
          for (auto &stream : streams)
              if (stream.fd >= 0 && (!gateway_ready || stopping || now() - stream.touched > 15000 || now() - stream.created > 300000)) stream.close();
          if (probe && probe->done && now() - probe->created > 30000) { delete probe; probe = nullptr; }
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
void network_init() {
    mutex = xSemaphoreCreateMutex(); ESP_ERROR_CHECK(mutex ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreate(janitor, "network-expiry", 3072, nullptr, 3, nullptr) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}
void register_network_commands(esp_openclaw_node_handle_t node) {
    ESP_ERROR_CHECK(esp_openclaw_node_register_capability(node, "network.transport.v1"));
    esp_openclaw_node_command_v2_t transport_cmd{};
    transport_cmd.name = "network.transport.v1"; transport_cmd.handler = command;
    ESP_ERROR_CHECK(esp_openclaw_node_register_command_v2(node, &transport_cmd));
    transport_cmd.name = "network.probe.v1"; transport_cmd.context = reinterpret_cast<void *>(1);
    ESP_ERROR_CHECK(esp_openclaw_node_register_command_v2(node, &transport_cmd));
}
}
