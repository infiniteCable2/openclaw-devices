#pragma once
#include "dns_sd.hpp"
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

namespace netnode::goe {
inline constexpr char id[] = "go-e";
inline constexpr char service[] = "_http";
inline constexpr char protocol[] = "_tcp";
inline constexpr uint16_t port = 80;
inline constexpr char status_path[] = "/api/status?filter=sse,car,alw,acu";
inline constexpr size_t status_max_bytes = 8192;
inline constexpr size_t max_devices_per_network = 8;

inline bool valid_key(std::string_view value) {
    if (value.size() != 6) return false;
    for (char c : value) if (c < '0' || c > '9') return false;
    return true;
}

enum class Match { other, serial_conflict, service_mismatch, name_fallback, identified };
struct Observation { Match match; bool named_target; };

Observation inspect(std::string_view instance, uint16_t announced_port,
                    const std::vector<TxtField> &txt, std::string_view key);
}
