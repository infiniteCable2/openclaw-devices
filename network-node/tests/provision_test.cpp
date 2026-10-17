// Compile the real persistence implementation against a fault-injectable NVS model.
#include "provision.hpp"
#include "setup_command.hpp"
#include <cassert>
#include <cstring>
#include <iostream>
#include <map>

static std::map<int, std::string> durable;
static std::string pending;
static bool staged = false;
static int durable_version = 0, pending_version = 0;
static int init_error = 0, write_error = 0, commit_error = 0, read_error = 0, random_calls = 0;
esp_err_t nvs_flash_init_partition(const char *name) {
    assert(!std::strcmp(name, "provision")); return init_error;
}
esp_err_t nvs_open_from_partition(const char *partition, const char *name, int mode, nvs_handle_t *out) {
    assert(!std::strcmp(partition, "provision") && !std::strcmp(name, "setup") && mode == NVS_READWRITE);
    *out = 2; return ESP_OK;
}
esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *value, size_t *size) {
    assert(!std::strcmp(key, "ap_password"));
    if (read_error) return read_error;
    if (!durable.count(handle)) return ESP_ERR_NVS_NOT_FOUND;
    const std::string &stored = durable.at(handle);
    size_t needed = stored.size() + 1;
    if (!value) { *size = needed; return ESP_OK; }
    if (*size < needed) return ESP_ERR_INVALID_SIZE;
    std::memcpy(value, stored.c_str(), needed); *size = needed; return ESP_OK;
}
esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value) {
    assert(handle == 2 && !std::strcmp(key, "ap_password"));
    if (write_error) return write_error;
    pending = value; staged = true; return ESP_OK;
}
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *value) {
    assert(handle == 2 && !std::strcmp(key, "version"));
    if (read_error) return read_error;
    if (!durable_version) return ESP_ERR_NVS_NOT_FOUND;
    *value = static_cast<uint8_t>(durable_version); return ESP_OK;
}
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value) {
    assert(handle == 2 && !std::strcmp(key, "version"));
    if (write_error) return write_error;
    pending_version = value; return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t handle) {
    assert(handle == 2);
    if (commit_error) return commit_error;
    if (staged) durable[handle] = pending;
    if (pending_version) durable_version = pending_version;
    staged = false; return ESP_OK;
}
void nvs_close(nvs_handle_t) { staged = false; pending.clear(); pending_version = 0; }
void esp_fill_random(void *out, size_t size) {
    ++random_calls;
    auto *bytes = static_cast<uint8_t *>(out);
    for (size_t i = 0; i < size; ++i) bytes[i] = static_cast<uint8_t>(i + random_calls);
}
esp_err_t esp_read_mac(uint8_t *out, int) {
    const uint8_t synthetic[] = {0x02, 0, 0, 0xab, 0xcd, 0xef};
    std::memcpy(out, synthetic, sizeof(synthetic)); return ESP_OK;
}
static void clean() {
    durable.clear(); pending.clear(); staged = false;
    durable_version = pending_version = 0;
    init_error = write_error = commit_error = read_error = random_calls = 0;
}
static bool feed(netnode::SetupCommand &command, const std::string &line) {
    bool accepted = false;
    for (char value : line) accepted |= command.feed(value);
    return accepted;
}
int main() {
    const std::string original = "0123456789abcdef01234567";
    std::string value;
    clean();
    durable[1] = original;
    assert(netnode::load_setup_password(1, value) == ESP_OK && value == original);
    assert(durable.at(2) == original && random_calls == 0);
    // Application reset erases only default NVS, including the old copy.
    durable.erase(1); value.clear();
    assert(netnode::load_setup_password(1, value) == ESP_OK && value == original);
    durable[1] = "ffffffffffffffffffffffff"; value.clear();
    assert(netnode::load_setup_password(1, value) == ESP_OK && value == original);
    assert(netnode::setup_ssid() == "OpenClaw-Setup-ABCDEF");
    clean();
    assert(netnode::load_setup_password(1, value) == ESP_OK && value.size() == 24);
    std::string fresh = value; durable.erase(1); value.clear();
    assert(netnode::load_setup_password(1, value) == ESP_OK && value == fresh && random_calls == 1);
    // An interrupted migration cannot publish an uncommitted replacement secret.
    clean(); durable[1] = original; commit_error = ESP_FAIL; value = "unchanged";
    assert(netnode::load_setup_password(1, value) == ESP_FAIL && value == "unchanged" && !durable.count(2));
    commit_error = 0;
    assert(netnode::load_setup_password(1, value) == ESP_OK && value == original);
    clean(); durable[1] = original; write_error = ESP_FAIL; value = "unchanged";
    assert(netnode::load_setup_password(1, value) == ESP_FAIL && value == "unchanged" && !durable.count(2));
    // Corruption/full/version errors must never erase the partition or regenerate stickers.
    clean(); init_error = ESP_FAIL; value = "unchanged";
    assert(netnode::load_setup_password(1, value) == ESP_FAIL && value == "unchanged" && random_calls == 0);
    clean(); durable[2] = "broken"; value = "unchanged";
    assert(netnode::load_setup_password(1, value) == ESP_ERR_INVALID_SIZE && value == "unchanged" && random_calls == 0);
    clean(); durable[2] = "gggggggggggggggggggggggg";
    assert(netnode::load_setup_password(1, value) == ESP_ERR_INVALID_ARG && random_calls == 0);
    clean(); durable[1] = "broken";
    assert(netnode::load_setup_password(1, value) == ESP_ERR_INVALID_SIZE && random_calls == 0);
    clean(); read_error = ESP_FAIL;
    assert(netnode::load_setup_password(1, value) == ESP_FAIL && random_calls == 0);
    clean(); durable_version = 1; value = "unchanged";
    assert(netnode::load_setup_password(1, value) == ESP_ERR_INVALID_STATE && value == "unchanged" && random_calls == 0);
    clean(); durable_version = 2; durable[2] = original;
    assert(netnode::load_setup_password(1, value) == ESP_ERR_INVALID_STATE && random_calls == 0);
    // Power loss after the password write but before its marker: finish, don't rotate.
    clean(); durable[2] = original;
    assert(netnode::load_setup_password(1, value) == ESP_OK && value == original && durable_version == 1 && random_calls == 0);
    netnode::SetupCommand command;
    assert(feed(command, "netnode setup-access v1\n"));
    assert(feed(command, "netnode setup-access v1\r\n"));
    assert(!feed(command, "netnode setup-access v2\n"));
    assert(!feed(command, std::string(1000, 'x') + "netnode setup-access v1\n"));
    assert(!feed(command, std::string("netnode setup-access v1\0", 24) + "\n"));
    assert(feed(command, "netnode setup-access v1\n"));
    std::cout << "Provision migration, reset retention, storage failures and serial framing passed.\n";
}
