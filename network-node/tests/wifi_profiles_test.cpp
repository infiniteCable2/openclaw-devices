#include "core.hpp"
#include <cassert>
#include <iostream>
#include <memory>
using namespace netnode;
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
static Settings parse(const char *text, const Settings &previous = {}) {
    Json json(cJSON_Parse(text), cJSON_Delete);
    Settings out; std::string error;
    assert(parse_settings(json.get(), previous, out, error)); return out;
}
static Json request(const Settings &settings) { return Json(settings_json(settings, false), cJSON_Delete); }
int main() {
    const Settings legacy = parse(R"({"ssid":"Example A","wifiPassword":"secret-a-123","dns":"192.0.2.53","context":"node1","gateway":"","mode":"allowlist","scan":false,"ping":false,"rules":[]})");
    assert(legacy.wifi_networks.size() == 1 && legacy.wifi_networks[0].password == "secret-a-123");
    Json json = request(legacy);
    cJSON *rows = cJSON_GetObjectItemCaseSensitive(json.get(), "wifiNetworks");
    cJSON *second = cJSON_Parse(R"({"ssid":"Hidden Example","wifiPassword":"secret-b-456","dns":"198.51.100.53","hidden":true})");
    cJSON_AddItemToArray(rows, second);
    cJSON_ReplaceItemInObjectCaseSensitive(json.get(), "ssid", cJSON_CreateString("Hidden Example"));
    Settings saved; std::string error;
    assert(parse_settings(json.get(), legacy, saved, error));
    assert(saved.wifi_networks.size() == 2 && saved.wifi_networks[0].password == "secret-a-123");
    assert(saved.wifi_networks[1].hidden && saved.wifi_password == "secret-b-456" && saved.dns == "198.51.100.53");
    Json stored(settings_json(saved, true), cJSON_Delete);
    Settings rebooted;
    assert(parse_settings(stored.get(), Settings{}, rebooted, error));
    assert(rebooted.wifi_networks[0].password == "secret-a-123" && rebooted.wifi_networks[1].password == "secret-b-456");
    // A previous firmware can still read its preferred-network projection.
    assert(std::string(cJSON_GetObjectItemCaseSensitive(stored.get(), "wifiPassword")->valuestring) == "secret-b-456");
    Json view = request(saved);
    char *raw = cJSON_PrintUnformatted(view.get());
    assert(std::string(raw).find("secret-") == std::string::npos); free(raw);
    rows = cJSON_GetObjectItemCaseSensitive(view.get(), "wifiNetworks");
    cJSON_DeleteItemFromArray(rows, 1); // Delete preferred; use remaining WLAN.
    cJSON_ReplaceItemInObjectCaseSensitive(view.get(), "ssid", cJSON_CreateString("Example A"));
    Settings removed;
    assert(parse_settings(view.get(), saved, removed, error));
    assert(removed.wifi_networks.size() == 1 && removed.wifi_password == "secret-a-123");
    // New SSIDs never inherit another network's password/DNS, even for old clients.
    cJSON_DeleteItemFromObjectCaseSensitive(view.get(), "wifiNetworks");
    cJSON_DeleteItemFromObjectCaseSensitive(view.get(), "dns");
    cJSON_ReplaceItemInObjectCaseSensitive(view.get(), "ssid", cJSON_CreateString("Example C"));
    cJSON_AddStringToObject(view.get(), "wifiPassword", "");
    Settings added;
    assert(parse_settings(view.get(), saved, added, error));
    assert(added.wifi_password.empty() && added.dns.empty() && added.wifi_networks.size() == 3);
    // Explicit credential removal affects only the selected profile.
    view = request(saved); rows = cJSON_GetObjectItemCaseSensitive(view.get(), "wifiNetworks");
    cJSON_AddBoolToObject(cJSON_GetArrayItem(rows, 1), "clearWifiPassword", true);
    assert(parse_settings(view.get(), saved, added, error));
    assert(added.wifi_networks[0].password == "secret-a-123" && added.wifi_networks[1].password.empty());
    cJSON_AddItemToArray(rows, cJSON_Duplicate(cJSON_GetArrayItem(rows, 0), true));
    assert(!parse_settings(view.get(), saved, added, error)); // Duplicate SSID.
    view = request(saved); rows = cJSON_GetObjectItemCaseSensitive(view.get(), "wifiNetworks");
    for (int i = 2; i < 9; ++i) {
        cJSON *row = cJSON_CreateObject(); cJSON_AddStringToObject(row, "ssid", ("Example " + std::to_string(i)).c_str());
        cJSON_AddItemToArray(rows, row);
        assert(parse_settings(view.get(), saved, added, error) == (i < 8));
    }
    view = request(saved); rows = cJSON_GetObjectItemCaseSensitive(view.get(), "wifiNetworks");
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(rows, 0), "dns", cJSON_CreateString("127.0.0.1"));
    assert(!parse_settings(view.get(), saved, added, error));
    view = request(saved); rows = cJSON_GetObjectItemCaseSensitive(view.get(), "wifiNetworks");
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(rows, 0), "hidden", cJSON_CreateString("yes"));
    assert(!parse_settings(view.get(), saved, added, error));
    // Removing the last profile leaves provisioning mode, with no stale secret.
    view = request(saved); cJSON_ReplaceItemInObjectCaseSensitive(view.get(), "wifiNetworks", cJSON_CreateArray());
    cJSON_ReplaceItemInObjectCaseSensitive(view.get(), "ssid", cJSON_CreateString(""));
    assert(parse_settings(view.get(), saved, added, error));
    assert(added.wifi_networks.empty() && added.wifi_password.empty() && added.dns.empty());
    assert(Settings{}.wifi_networks.empty()); // No factory-reset default profile.
    assert(valid_ssid(" Hidden Example ") && valid_ssid("Caf\xc3\xa9") && valid_ssid(std::string(32, 'x')));
    assert(!valid_ssid("") && !valid_ssid(std::string(33, 'x')) && !valid_ssid("bad\nSSID"));
    assert(!valid_ssid("\xc0\xaf") && !valid_ssid("\xed\xa0\x80") && !valid_ssid("\xf4\x90\x80\x80"));
    std::cout << "Wi-Fi migration, reboot roundtrip, redaction, deletion, hidden SSID, DNS and credential-isolation checks passed\n";
}
