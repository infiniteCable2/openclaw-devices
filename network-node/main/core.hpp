#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include "cJSON.h"

namespace netnode {
constexpr size_t max_body = 12288;
constexpr size_t max_chunk = 2048;
constexpr size_t max_datagram = 1200;
constexpr size_t max_streams = 4;
constexpr size_t max_scan_targets = 32;
constexpr size_t max_wifi_networks = 8;

enum class Protocol { tcp, udp, icmp };
struct Rule {
    uint32_t network = 0;
    uint8_t prefix = 32;
    Protocol protocol = Protocol::tcp;
    uint16_t first = 1, last = 65535;
    std::string mac;
};
struct WifiProfile {
    std::string ssid, password, dns;
    bool hidden = false;
};
struct Settings {
    // Preferred profile projection retained for older local clients/firmware.
    std::string ssid, wifi_password, dns;
    std::vector<WifiProfile> wifi_networks;
    std::string context = "node1";
    std::string gateway, ca;
    bool admin = false;
    bool scan = false, ping = false;
    std::vector<Rule> rules;
};
bool ipv4(const std::string &text, uint32_t &address);
std::string ip_text(uint32_t address);
bool wss_url(const std::string &text);
bool identifier(const std::string &text);
bool parse_settings(const cJSON *json, const Settings &previous, Settings &out, std::string &error);
cJSON *settings_json(const Settings &settings, bool secrets);
bool allows(const Settings &settings, uint32_t address, Protocol protocol, uint16_t port,
            const std::string &observed_mac = "");
bool needs_mac(const Settings &settings, uint32_t address, Protocol protocol, uint16_t port);
bool valid_target(uint32_t address, Protocol protocol);
const char *protocol_name(Protocol protocol);
bool integer(const cJSON *object, const char *name, int minimum, int maximum, int &out);
bool string_field(const cJSON *object, const char *name, size_t maximum, std::string &out);
bool valid_ssid(const std::string &text);
}
