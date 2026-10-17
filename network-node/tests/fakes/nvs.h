#pragma once
#include <cstddef>
#include <cstdint>
#include <stdexcept>
using esp_err_t = int;
using nvs_handle_t = int;
constexpr int ESP_OK = 0, ESP_FAIL = -1;
constexpr int ESP_ERR_NVS_NOT_FOUND = 1, ESP_ERR_INVALID_SIZE = 2, ESP_ERR_INVALID_ARG = 3;
constexpr int ESP_ERR_INVALID_STATE = 4;
constexpr int NVS_READWRITE = 1;
#define ESP_ERROR_CHECK(result) do { if ((result) != ESP_OK) throw std::runtime_error("ESP error"); } while (false)
esp_err_t nvs_open_from_partition(const char *, const char *, int, nvs_handle_t *);
esp_err_t nvs_get_str(nvs_handle_t, const char *, char *, size_t *);
esp_err_t nvs_set_str(nvs_handle_t, const char *, const char *);
esp_err_t nvs_get_u8(nvs_handle_t, const char *, uint8_t *);
esp_err_t nvs_set_u8(nvs_handle_t, const char *, uint8_t);
esp_err_t nvs_commit(nvs_handle_t);
void nvs_close(nvs_handle_t);
