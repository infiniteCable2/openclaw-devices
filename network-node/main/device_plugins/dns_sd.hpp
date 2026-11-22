#pragma once
#include <cstdint>
#include <string_view>
#include <vector>

namespace netnode {
struct TxtField { std::string_view key, value; bool has_value; };

struct DnsSdService {
    std::string_view instance;
    uint16_t port;
    std::vector<TxtField> txt;
    std::vector<uint32_t> addresses;
};
}
