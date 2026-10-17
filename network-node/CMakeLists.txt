cmake_minimum_required(VERSION 3.16)

# Select hardware explicitly; shared protocol/security code stays in main/.
set(NETWORK_NODE_BOARD "esp32-4mb" CACHE STRING "Network node board profile")
set(_supported_boards esp32-4mb esp32s3-16mb)
if(NOT NETWORK_NODE_BOARD IN_LIST _supported_boards)
    message(FATAL_ERROR "Unsupported NETWORK_NODE_BOARD: ${NETWORK_NODE_BOARD}")
endif()
set(NETWORK_NODE_BOARD_DIR "${CMAKE_CURRENT_LIST_DIR}/boards/${NETWORK_NODE_BOARD}")
include("${NETWORK_NODE_BOARD_DIR}/profile.cmake")
if(DEFINED IDF_TARGET AND NOT IDF_TARGET STREQUAL NETWORK_NODE_TARGET)
    message(FATAL_ERROR "Board ${NETWORK_NODE_BOARD} requires IDF_TARGET=${NETWORK_NODE_TARGET}")
endif()
set(IDF_TARGET "${NETWORK_NODE_TARGET}" CACHE STRING "ESP-IDF target" FORCE)
set(SDKCONFIG_DEFAULTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults;${NETWORK_NODE_BOARD_DIR}/sdkconfig.defaults")
if(NOT DEFINED SDKCONFIG)
    set(SDKCONFIG "${CMAKE_BINARY_DIR}/sdkconfig")
endif()

# Add a local component only when that board actually needs a variant.
if(IS_DIRECTORY "${NETWORK_NODE_BOARD_DIR}/components")
    list(APPEND EXTRA_COMPONENT_DIRS "${NETWORK_NODE_BOARD_DIR}/components")
endif()
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(DEPENDENCIES_LOCK "${NETWORK_NODE_BOARD_DIR}/dependencies.lock")
project(openclaw_network_node)

if(NOT CONFIG_ESPTOOLPY_FLASHSIZE STREQUAL NETWORK_NODE_FLASH_SIZE OR
   NOT CONFIG_PARTITION_TABLE_CUSTOM OR
   NOT CONFIG_PARTITION_TABLE_CUSTOM_FILENAME STREQUAL NETWORK_NODE_PARTITIONS)
    message(FATAL_ERROR "Stale/incompatible sdkconfig for ${NETWORK_NODE_BOARD}; regenerate it in a clean build directory")
endif()
