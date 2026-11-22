idf_component_register(
    SRCS "app.cpp" "wifi.cpp" "core.cpp" "settings.cpp" "network.cpp" "web.cpp" "provision.cpp" "setup_console.cpp"
          "device_plugins/managed_device.cpp" "device_plugins/device_network.cpp"
          "device_plugins/goe.cpp" "device_plugins/goe_profile.cpp"
    INCLUDE_DIRS "." "${NETWORK_NODE_BOARD_DIR}/include"
    EMBED_TXTFILES "portal.html"
    REQUIRES esp_wifi esp_event esp_netif esp_http_server esp_http_client nvs_flash esp_timer driver esp_driver_uart lwip mbedtls bootloader_support)
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
