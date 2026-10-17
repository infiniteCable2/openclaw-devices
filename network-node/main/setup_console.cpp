#include "settings.hpp"
#include "provision.hpp"
#include "setup_command.hpp"
#include <cstdio>
#include "driver/uart.h"
#include "esp_timer.h"
#include "mbedtls/sha256.h"
#include "sdkconfig.h"

#if !CONFIG_ESP_CONSOLE_UART_DEFAULT
#error "Setup USB access requires the board's UART console profile"
#endif

namespace netnode {
static std::string access_checksum;
void setup_console_poll() {
    // Reuse the existing application loop; no additional task or task stack.
    static SetupCommand command;
    static int64_t next_reply = 0;
    uint8_t bytes[64];
    int count = uart_read_bytes(static_cast<uart_port_t>(CONFIG_ESP_CONSOLE_UART_NUM),
        bytes, sizeof(bytes), 0);
    for (int i = 0; i < count; ++i) {
        if (!command.feed(static_cast<char>(bytes[i]))) continue;
        int64_t now = esp_timer_get_time();
        if (stopping || now < next_reply) continue;
        next_reply = now + 1000000;
        // Only immutable, hex-validated sticker data; no LAN/Gateway/session secrets.
        std::printf("\n{\"type\":\"netnode.setup-access\",\"version\":1,\"ssid\":\"%s\","
            "\"password\":\"%s\",\"username\":\"admin\",\"url\":\"http://192.168.4.1\",\"sha256\":\"%s\"}\n",
            setup_ssid().c_str(), ap_password.c_str(), access_checksum.c_str());
        std::fflush(stdout);
    }
}
void setup_console_start() {
    std::string data = setup_ssid() + "\n" + ap_password;
    unsigned char digest[32];
    ESP_ERROR_CHECK(mbedtls_sha256(reinterpret_cast<const unsigned char *>(data.data()), data.size(), digest, 0));
    for (unsigned char byte : digest) {
        access_checksum += "0123456789abcdef"[byte >> 4];
        access_checksum += "0123456789abcdef"[byte & 15];
    }
    constexpr uart_port_t port = static_cast<uart_port_t>(CONFIG_ESP_CONSOLE_UART_NUM);
    ESP_ERROR_CHECK(uart_driver_install(port, 512, 0, 0, nullptr, 0));
}
}
