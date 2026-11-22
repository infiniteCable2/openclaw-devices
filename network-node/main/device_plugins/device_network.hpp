#pragma once
#include "dns_sd.hpp"
#include "managed_device.hpp"
#include <cstddef>

namespace netnode {
enum class DeviceNetworkError { none, wifi_changed, unavailable, timeout, rejected, response_too_large };

// The visitor runs synchronously while the native mDNS response is owned here.
using ServiceVisitor = bool (*)(const DnsSdService &, void *);
DeviceNetworkError visit_local_services(const ManagedDeviceLink &link, const char *service, const char *protocol,
                                       uint32_t timeout_ms, ServiceVisitor visit, void *context);

struct DeviceHttpResponse {
    std::string body;
    DeviceNetworkError error = DeviceNetworkError::none;
};

// The path and limits come from the compiled device plugin.
DeviceHttpResponse read_local_json(const ManagedDeviceLink &link, uint32_t address, uint16_t port, const char *path,
                                   size_t max_bytes, int64_t deadline);
}
