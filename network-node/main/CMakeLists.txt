idf_component_register(
    SRCS "app.cpp" "core.cpp" "settings.cpp" "network.cpp" "web.cpp"
    INCLUDE_DIRS "." "${CMAKE_CURRENT_BINARY_DIR}"
    REQUIRES esp_wifi esp_event esp_netif esp_http_server nvs_flash esp_timer driver lwip mbedtls bootloader_support)
file(READ "${CMAKE_CURRENT_LIST_DIR}/portal.html" PORTAL_HTML)
configure_file("${CMAKE_CURRENT_LIST_DIR}/portal.hpp.in" "${CMAKE_CURRENT_BINARY_DIR}/portal.hpp" @ONLY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/portal.html")
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
