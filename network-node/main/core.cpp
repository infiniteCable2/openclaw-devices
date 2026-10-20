#include "core.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace netnode {
static const cJSON *item(const cJSON *json, const char *name) {
    return cJSON_GetObjectItemCaseSensitive(json, name);
}
bool string_field(const cJSON *json, const char *name, size_t maximum, std::string &out) {
    auto value = item(json, name);
    if (!cJSON_IsString(value) || !value->valuestring) return false;
    out = value->valuestring;
    if (out.size() > maximum) return false;
    for (unsigned char c : out) if (c < 32 || c == 127) return false;
    return true;
}
bool integer(const cJSON *json, const char *name, int minimum, int maximum, int &out) {
    auto value = item(json, name);
    if (!cJSON_IsNumber(value) || !std::isfinite(value->valuedouble) ||
        std::floor(value->valuedouble) != value->valuedouble ||
        value->valuedouble < minimum || value->valuedouble > maximum) return false;
    out = static_cast<int>(value->valuedouble);
    return true;
}
bool identifier(const std::string &text) {
    if (text.empty() || text.size() > 48 || text == "local") return false;
    for (char c : text) if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_')) return false;
    return true;
}
bool ipv4(const std::string &text, uint32_t &address) {
    address = 0;
    size_t cursor = 0;
    for (int part = 0; part < 4; ++part) {
        size_t start = cursor;
        unsigned n = 0;
        while (cursor < text.size() && text[cursor] >= '0' && text[cursor] <= '9') {
            n = n * 10 + unsigned(text[cursor++] - '0');
            if (cursor - start > 3 || n > 255) return false;
        }
        if (cursor == start || (cursor - start > 1 && text[start] == '0')) return false;
        address = (address << 8) | n;
        if (part < 3 && (cursor >= text.size() || text[cursor++] != '.')) return false;
    }
    return cursor == text.size();
}
std::string ip_text(uint32_t address) {
    char text[16];
    std::snprintf(text, sizeof(text), "%u.%u.%u.%u", unsigned(address >> 24), unsigned((address >> 16) & 255),
                  unsigned((address >> 8) & 255), unsigned(address & 255));
    return text;
}
bool wss_url(const std::string &text) {
    if (text.size() < 7 || text.size() > 256 || text.compare(0, 6, "wss://") != 0) return false;
    if (text.find_first_of("@?#\\|\r\n\t ") != std::string::npos) return false;
    auto end = text.find('/', 6);
    std::string authority = text.substr(6, end == std::string::npos ? end : end - 6);
    if (authority.empty()) return false;
    // IPv4/DNS only in v1; reject ambiguous authority encodings.
    auto colon = authority.find(':');
    std::string host = authority.substr(0, colon);
    if (host.empty()) return false;
    for (char c : host) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || c == '.' || c == '-')) return false;
    if (colon != std::string::npos) {
        std::string port = authority.substr(colon + 1);
        if (port.empty() || port.size() > 5) return false;
        unsigned n = 0;
        for (char c : port) { if (c < '0' || c > '9') return false; n = n * 10 + unsigned(c - '0'); }
        if (!n || n > 65535) return false;
    }
    return true;
}
const char *protocol_name(Protocol protocol) {
    return protocol == Protocol::tcp ? "tcp" : protocol == Protocol::udp ? "udp" : "icmp";
}
static uint32_t mask(uint8_t prefix) { return prefix == 0 ? 0 : UINT32_MAX << (32 - prefix); }
static bool target_match(const Rule &rule, uint32_t address, Protocol protocol, uint16_t port) {
    return rule.protocol == protocol && (address & mask(rule.prefix)) == rule.network &&
           (protocol == Protocol::icmp || (port >= rule.first && port <= rule.last));
}
bool valid_target(uint32_t address, Protocol protocol) {
    const uint8_t first = address >> 24;
    if (!first || first == 127 || (address & 0xffff0000U) == 0xa9fe0000U) return false;
    if (first >= 224) return protocol == Protocol::udp && (first < 240 || address == UINT32_MAX);
    return true;
}
bool allows(const Settings &settings, uint32_t address, Protocol protocol, uint16_t port,
            const std::string &observed_mac) {
    if (!valid_target(address, protocol) || (protocol != Protocol::icmp && !port)) return false;
    if (settings.admin) return true;
    for (const auto &rule : settings.rules)
        if (target_match(rule, address, protocol, port) && (rule.mac.empty() || rule.mac == observed_mac)) return true;
    return false;
}
bool needs_mac(const Settings &settings, uint32_t address, Protocol protocol, uint16_t port) {
    if (settings.admin) return false;
    for (const auto &rule : settings.rules)
        if (target_match(rule, address, protocol, port) && !rule.mac.empty()) return true;
    return false;
}
static bool boolean(const cJSON *json, const char *name, bool &out) {
    auto value = item(json, name);
    if (!cJSON_IsBool(value)) return false;
    out = cJSON_IsTrue(value);
    return true;
}
bool valid_ssid(const std::string &text) {
    if (text.empty() || text.size() > 32) return false;
    for (size_t i = 0; i < text.size();) {
        unsigned char c = text[i++];
        if (c < 32 || c == 127) return false;
        if (c < 128) continue;
        unsigned need, code, minimum;
        if (c >= 0xc2 && c <= 0xdf) { need = 1; code = c & 31; minimum = 0x80; }
        else if (c >= 0xe0 && c <= 0xef) { need = 2; code = c & 15; minimum = 0x800; }
        else if (c >= 0xf0 && c <= 0xf4) { need = 3; code = c & 7; minimum = 0x10000; }
        else return false;
        if (i + need > text.size()) return false;
        while (need--) { c = text[i++]; if ((c & 0xc0) != 0x80) return false; code = (code << 6) | (c & 63); }
        if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return false;
    }
    return true;
}
static const WifiProfile *find_wifi(const std::vector<WifiProfile> &profiles, const std::string &ssid) {
    for (const auto &profile : profiles) if (profile.ssid == ssid) return &profile;
    return nullptr;
}
static bool wifi_fields(const cJSON *json, WifiProfile &profile, std::string &error) {
    auto fail = [&error](const char *message) { error = message; return false; };
    if (item(json, "wifiPassword")) {
        std::string value;
        if (!string_field(json, "wifiPassword", 63, value)) return fail("Invalid Wi-Fi password");
        if (!value.empty()) profile.password = value;
    }
    auto clear = item(json, "clearWifiPassword");
    if (clear && !cJSON_IsBool(clear)) return fail("Invalid clearWifiPassword");
    if (cJSON_IsTrue(clear)) profile.password.clear();
    if (!profile.password.empty() && profile.password.size() < 8) return fail("Wi-Fi password needs 8-63 bytes");
    if (item(json, "dns")) {
        uint32_t address;
        if (!string_field(json, "dns", 15, profile.dns) || (!profile.dns.empty() &&
            (!ipv4(profile.dns, address) || !valid_target(address, Protocol::tcp))))
            return fail("DNS server must be a canonical unicast IPv4 address or blank");
    }
    if (item(json, "hidden") && !boolean(json, "hidden", profile.hidden)) return fail("Invalid hidden SSID flag");
    return true;
}
bool parse_settings(const cJSON *json, const Settings &previous, Settings &out, std::string &error) {
    auto fail = [&error](const char *message) { error = message; return false; };
    if (!cJSON_IsObject(json)) return fail("Expected settings object");
    out = previous;
    if (!string_field(json, "ssid", 32, out.ssid) ||
        !string_field(json, "context", 48, out.context) || !identifier(out.context) ||
        !string_field(json, "gateway", 256, out.gateway) || (!out.gateway.empty() && !wss_url(out.gateway)))
        return fail("Invalid Wi-Fi, context ID or wss:// Gateway URL");
    std::vector<WifiProfile> prior = previous.wifi_networks;
    if (prior.empty() && !previous.ssid.empty())
        prior.push_back({previous.ssid, previous.wifi_password, previous.dns, false});
    auto networks = item(json, "wifiNetworks");
    if (networks) {
        if (!cJSON_IsArray(networks) || cJSON_GetArraySize(networks) > int(max_wifi_networks))
            return fail("At most 8 saved Wi-Fi networks");
        out.wifi_networks.clear();
        const cJSON *row;
        cJSON_ArrayForEach(row, networks) {
            WifiProfile profile;
            if (!string_field(row, "ssid", 32, profile.ssid) || !valid_ssid(profile.ssid)) return fail("Invalid saved SSID");
            if (find_wifi(out.wifi_networks, profile.ssid)) return fail("Duplicate saved SSID");
            if (auto saved = find_wifi(prior, profile.ssid)) profile = *saved;
            if (!wifi_fields(row, profile, error)) return false;
            out.wifi_networks.push_back(profile);
        }
        if (out.ssid.empty() && !out.wifi_networks.empty()) out.ssid = out.wifi_networks.front().ssid;
        if (!out.ssid.empty() && !find_wifi(out.wifi_networks, out.ssid)) return fail("Preferred SSID must be saved");
    } else {
        // Migrate the original single-network NVS object and accept old clients.
        out.wifi_networks = prior;
        if (out.ssid.empty()) out.wifi_networks.clear();
        else {
            if (!valid_ssid(out.ssid)) return fail("Invalid SSID");
            WifiProfile profile{out.ssid, "", "", false};
            if (auto saved = find_wifi(prior, out.ssid)) profile = *saved;
            // A blank password never copies another SSID's credential or DNS.
            if (!wifi_fields(json, profile, error)) return false;
            bool replaced = false;
            for (auto &saved : out.wifi_networks) if (saved.ssid == profile.ssid) { saved = profile; replaced = true; break; }
            if (!replaced) {
                if (out.wifi_networks.size() >= max_wifi_networks) return fail("At most 8 saved Wi-Fi networks");
                out.wifi_networks.push_back(profile);
            }
        }
    }
    out.wifi_password.clear(); out.dns.clear();
    if (auto preferred = find_wifi(out.wifi_networks, out.ssid)) {
        out.wifi_password = preferred->password; out.dns = preferred->dns;
    }
    auto ca = item(json, "ca");
    if (ca) {
        if (!cJSON_IsString(ca) || !ca->valuestring) return fail("Invalid CA certificate");
        out.ca = ca->valuestring;
        if (out.ca.size() > 4096 || (!out.ca.empty() &&
            out.ca.find("-----BEGIN CERTIFICATE-----") != 0)) return fail("Expected a PEM CA certificate");
    }
    std::string mode;
    if (!string_field(json, "mode", 16, mode) || (mode != "allowlist" && mode != "admin") ||
        !boolean(json, "scan", out.scan) || !boolean(json, "ping", out.ping)) return fail("Invalid operating mode");
    out.admin = mode == "admin";
    auto rules = item(json, "rules");
    if (!cJSON_IsArray(rules) || cJSON_GetArraySize(rules) > 32) return fail("At most 32 allowlist rules");
    out.rules.clear();
    const cJSON *row;
    cJSON_ArrayForEach(row, rules) {
        Rule rule;
        std::string cidr, protocol;
        int first, last;
        if (!string_field(row, "cidr", 18, cidr) || !string_field(row, "protocol", 4, protocol) ||
            !integer(row, "first", 0, 65535, first) || !integer(row, "last", first, 65535, last))
            return fail("Invalid allowlist rule");
        auto slash = cidr.find('/');
        if (!ipv4(cidr.substr(0, slash), rule.network)) return fail("Use canonical IPv4 or CIDR targets");
        if (slash != std::string::npos) {
            std::string bits = cidr.substr(slash + 1);
            if (bits.empty() || bits.size() > 2) return fail("Invalid CIDR prefix");
            unsigned prefix = 0;
            for (char c : bits) { if (c < '0' || c > '9') return fail("Invalid CIDR prefix"); prefix = prefix * 10 + unsigned(c - '0'); }
            if (prefix > 32) return fail("Invalid CIDR prefix");
            rule.prefix = prefix;
        }
        if ((rule.network & mask(rule.prefix)) != rule.network) return fail("CIDR must use its network address");
        if (protocol == "tcp") rule.protocol = Protocol::tcp;
        else if (protocol == "udp") rule.protocol = Protocol::udp;
        else if (protocol == "icmp") rule.protocol = Protocol::icmp;
        else return fail("Protocol must be tcp, udp or icmp");
        if (rule.protocol == Protocol::icmp ? (first != 0 || last != 0) : first == 0)
            return fail("ICMP uses port 0; TCP/UDP use ports 1-65535");
        rule.first = first; rule.last = last;
        if (item(row, "mac")) {
            if (!string_field(row, "mac", 17, rule.mac)) return fail("Invalid MAC");
            if (!rule.mac.empty()) {
                if (rule.mac.size() != 17 || rule.prefix != 32) return fail("MAC pin requires one IPv4 /32 target");
                for (size_t i = 0; i < rule.mac.size(); ++i) {
                    char &c = rule.mac[i];
                    if (i % 3 == 2) { if (c != ':') return fail("Invalid MAC"); }
                    else { if (c >= 'A' && c <= 'F') c += 'a' - 'A'; if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return fail("Invalid MAC"); }
                }
                if ((std::strtoul(rule.mac.substr(0, 2).c_str(), nullptr, 16) & 1) || rule.mac == "00:00:00:00:00:00")
                    return fail("MAC must be a unicast device address");
            }
        }
        out.rules.push_back(rule);
    }
    return true;
}
cJSON *settings_json(const Settings &settings, bool secrets) {
    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "ssid", settings.ssid.c_str());
    cJSON_AddStringToObject(json, "dns", settings.dns.c_str());
    cJSON_AddStringToObject(json, "context", settings.context.c_str());
    cJSON_AddStringToObject(json, "gateway", settings.gateway.c_str());
    cJSON_AddStringToObject(json, "ca", settings.ca.c_str());
    cJSON_AddStringToObject(json, "mode", settings.admin ? "admin" : "allowlist");
    cJSON_AddBoolToObject(json, "scan", settings.scan);
    cJSON_AddBoolToObject(json, "ping", settings.ping);
    cJSON_AddBoolToObject(json, "wifiPasswordSet", !settings.wifi_password.empty());
    if (secrets) cJSON_AddStringToObject(json, "wifiPassword", settings.wifi_password.c_str());
    cJSON *networks = cJSON_AddArrayToObject(json, "wifiNetworks");
    for (const auto &profile : settings.wifi_networks) {
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "ssid", profile.ssid.c_str());
        cJSON_AddStringToObject(row, "dns", profile.dns.c_str());
        cJSON_AddBoolToObject(row, "hidden", profile.hidden);
        cJSON_AddBoolToObject(row, "wifiPasswordSet", !profile.password.empty());
        if (secrets) cJSON_AddStringToObject(row, "wifiPassword", profile.password.c_str());
        cJSON_AddItemToArray(networks, row);
    }
    cJSON *rules = cJSON_AddArrayToObject(json, "rules");
    for (const auto &rule : settings.rules) {
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "cidr", (ip_text(rule.network) + "/" + std::to_string(rule.prefix)).c_str());
        cJSON_AddStringToObject(row, "protocol", protocol_name(rule.protocol));
        cJSON_AddNumberToObject(row, "first", rule.first);
        cJSON_AddNumberToObject(row, "last", rule.last);
        cJSON_AddStringToObject(row, "mac", rule.mac.c_str());
        cJSON_AddItemToArray(rules, row);
    }
    return json;
}
}
