#include "core.hpp"
#include <cassert>
#include <iostream>
using namespace netnode;

int main() {
    std::string deep(20, '['); deep += "0"; deep += std::string(20, ']');
    cJSON *nested = cJSON_Parse(deep.c_str());
    assert(nested == nullptr); // Match the firmware's bounded cJSON configuration.
    uint32_t address;
    assert(ipv4("192.0.2.10", address) && ip_text(address) == "192.0.2.10");
    for (const char *invalid : {"127.1", "0177.0.0.1", "192.0.2.256", "192.0.2.1:80", "192.0.2.1x", "-1.0.0.1", "4294967297.0.0.1"})
        assert(!ipv4(invalid, address));
    assert(wss_url("wss://gateway.example.org:8443/node"));
    for (const char *invalid : {"ws://gateway.example.org", "wss://user@gateway.example.org", "wss://host:0", "wss://host:65536", "wss://host:443junk", "wss:///", "wss://host?token=x", "wss://host\\evil"})
        assert(!wss_url(invalid));
    assert(!identifier("local") && !identifier("../node") && identifier("node1"));
    Settings defaults;
    assert(ipv4("192.0.2.10", address));
    assert(!allows(defaults, address, Protocol::tcp, 443));
    const char *raw = R"({"ssid":"Example WiFi","context":"node1","gateway":"wss://gateway.example.org","mode":"allowlist","ping":true,"scan":true,"rules":[{"cidr":"192.0.2.0/24","protocol":"tcp","first":443,"last":443},{"cidr":"192.0.2.10","protocol":"icmp","first":0,"last":0},{"cidr":"192.0.2.11","protocol":"udp","first":9,"last":9,"mac":"02:00:00:00:00:11"}]})";
    cJSON *json = cJSON_Parse(raw);
    Settings config; std::string error;
    defaults.wifi_password = "example-password";
    assert(parse_settings(json, defaults, config, error));
    assert(config.wifi_password == defaults.wifi_password);
    assert(config.dns.empty()); // Existing NVS objects remain readable.
    cJSON_AddStringToObject(json, "dns", "192.0.2.53");
    assert(parse_settings(json, defaults, config, error));
    assert(config.dns == "192.0.2.53");
    cJSON *persisted = settings_json(config, true);
    Settings restored;
    assert(parse_settings(persisted, Settings{}, restored, error));
    assert(restored.dns == config.dns && restored.wifi_password == defaults.wifi_password);
    cJSON_Delete(persisted);
    cJSON_DeleteItemFromObjectCaseSensitive(json, "dns");
    assert(parse_settings(json, config, restored, error) && restored.dns == config.dns);
    cJSON_AddStringToObject(json, "dns", "");
    assert(parse_settings(json, config, restored, error) && restored.dns.empty());
    for (const char *invalid : {"0.0.0.0", "127.0.0.1", "169.254.1.1", "224.0.0.1",
             "255.255.255.255", "192.000.2.53", "192.0.2.53:53", "resolver.example.org"}) {
        cJSON_ReplaceItemInObjectCaseSensitive(json, "dns", cJSON_CreateString(invalid));
        assert(!parse_settings(json, defaults, restored, error));
    }
    cJSON_ReplaceItemInObjectCaseSensitive(json, "dns", cJSON_CreateNull());
    assert(!parse_settings(json, defaults, restored, error));
    cJSON_DeleteItemFromObjectCaseSensitive(json, "dns");
    assert(allows(config, address, Protocol::tcp, 443));
    assert(!allows(config, address, Protocol::tcp, 80));
    assert(!allows(config, address, Protocol::udp, 443));
    assert(allows(config, address, Protocol::icmp, 0));
    assert(ipv4("192.0.2.11", address));
    assert(!allows(config, address, Protocol::udp, 9));
    assert(needs_mac(config, address, Protocol::udp, 9));
    assert(!allows(config, address, Protocol::udp, 9, "02:00:00:00:00:12"));
    assert(allows(config, address, Protocol::udp, 9, "02:00:00:00:00:11"));
    cJSON *rules = cJSON_GetObjectItemCaseSensitive(json, "rules");
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(rules, 0), "cidr", cJSON_CreateString("192.0.2.1/24"));
    assert(!parse_settings(json, defaults, config, error));
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(rules, 0), "cidr", cJSON_CreateString("192.0.2.0/24"));
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(rules, 0), "first", cJSON_CreateNumber(1.5));
    assert(!parse_settings(json, defaults, config, error));
    cJSON_Delete(json);
    config.admin = true;
    for (const char *invalid : {"0.0.0.0", "127.0.0.1", "169.254.169.254", "224.0.0.1"}) {
        assert(ipv4(invalid, address)); assert(!allows(config, address, Protocol::tcp, 443));
    }
    cJSON *view = settings_json(defaults, false);
    assert(!cJSON_GetObjectItemCaseSensitive(view, "wifiPassword"));
    cJSON_Delete(view);
    std::cout << "policy, configuration, target and credential-redaction checks passed\n";
}
