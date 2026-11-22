#include "goe_profile.hpp"

namespace netnode::goe {
namespace {
constexpr std::string_view instance_prefix = "go-eCharger_";
constexpr std::string_view type_prefix = "go-eCharger";

char ascii_lower(char c) { return c >= 'A' && c <= 'Z' ? char(c - 'A' + 'a') : c; }
bool equals(std::string_view a, std::string_view b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i) if (ascii_lower(a[i]) != ascii_lower(b[i])) return false;
    return true;
}
bool starts_with(std::string_view text, std::string_view prefix) {
    return equals(text.substr(0, prefix.size()), prefix);
}
struct Field {
    size_t count = 0;
    bool has_value = false;
    std::string_view value;
};
Field field(const std::vector<TxtField> &txt, std::string_view key) {
    Field result;
    for (const auto &entry : txt) {
        if (!equals(entry.key, key)) continue;
        ++result.count;
        result.has_value = entry.has_value;
        result.value = entry.value;
    }
    return result;
}
}

Observation inspect(std::string_view instance, uint16_t announced_port,
                    const std::vector<TxtField> &txt, std::string_view key) {
    auto suffix = starts_with(instance, instance_prefix) ? instance.substr(instance_prefix.size()) : std::string_view{};
    bool named = valid_key(key) && suffix == key;
    auto serial = field(txt, "serial");
    bool serial_matches = valid_key(key) && serial.count == 1 && serial.has_value && serial.value == key;
    bool fallback = named && serial.count == 0;
    if ((!serial_matches && !fallback) || (serial_matches && valid_key(suffix) && !named))
        return {named || serial_matches ? Match::serial_conflict : Match::other, named};
    auto manufacturer = field(txt, "manufacturer");
    auto device_type = field(txt, "devicetype");
    bool manufacturer_ok = manufacturer.count == 1 && manufacturer.has_value && equals(manufacturer.value, "go-e");
    bool type_ok = device_type.count == 1 && device_type.has_value && starts_with(device_type.value, type_prefix);
    if (announced_port != port || (!manufacturer_ok && !(fallback && manufacturer.count == 0)) ||
        (!type_ok && !(fallback && device_type.count == 0))) return {Match::service_mismatch, named};
    return {fallback ? Match::name_fallback : Match::identified, named};
}
}
