cmake_minimum_required(VERSION 3.20)

project(
  native_mcp_sandbox
  VERSION 0.4.0
  DESCRIPTION "A security-first, resource-bounded C++20 foundation for local MCP analysis tools"
  LANGUAGES CXX
)

include(CTest)
include(GNUInstallDirs)

option(NMS_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(NMS_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

find_package(nlohmann_json 3.11 QUIET)
if(NOT TARGET nlohmann_json::nlohmann_json)
  find_path(NLOHMANN_JSON_INCLUDE_DIR nlohmann/json.hpp REQUIRED)
  add_library(nlohmann_json_header_only INTERFACE)
  add_library(nlohmann_json::nlohmann_json ALIAS nlohmann_json_header_only)
  target_include_directories(nlohmann_json_header_only INTERFACE
    ${NLOHMANN_JSON_INCLUDE_DIR}
  )
endif()

function(nms_set_project_warnings target)
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(${target} PRIVATE
      -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
    )
    if(NMS_WARNINGS_AS_ERRORS)
      target_compile_options(${target} PRIVATE -Werror)
    endif()
  endif()
endfunction()

function(nms_enable_sanitizers target)
  if(NMS_ENABLE_SANITIZERS)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
      target_compile_options(${target} PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer
      )
      target_link_options(${target} PRIVATE -fsanitize=address,undefined)
    else()
      message(FATAL_ERROR "NMS_ENABLE_SANITIZERS requires GCC or Clang")
    endif()
  endif()
endfunction()

add_library(native_mcp_foundation STATIC
  src/foundation.cpp
)
add_library(native_mcp::foundation ALIAS native_mcp_foundation)
target_compile_features(native_mcp_foundation PUBLIC cxx_std_20)
target_include_directories(native_mcp_foundation
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
nms_set_project_warnings(native_mcp_foundation)
nms_enable_sanitizers(native_mcp_foundation)

add_library(native_mcp_policy STATIC
  src/file_policy.cpp
)
add_library(native_mcp::policy ALIAS native_mcp_policy)
target_compile_features(native_mcp_policy PUBLIC cxx_std_20)
target_include_directories(native_mcp_policy
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_link_libraries(native_mcp_policy
  PUBLIC native_mcp::foundation nlohmann_json::nlohmann_json
)
nms_set_project_warnings(native_mcp_policy)
nms_enable_sanitizers(native_mcp_policy)

add_library(native_mcp_log_tools STATIC
  src/log_analysis.cpp
  src/log_tools.cpp
)
add_library(native_mcp::log_tools ALIAS native_mcp_log_tools)
target_compile_features(native_mcp_log_tools PUBLIC cxx_std_20)
target_include_directories(native_mcp_log_tools
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_link_libraries(native_mcp_log_tools
  PUBLIC native_mcp::policy nlohmann_json::nlohmann_json
)
nms_set_project_warnings(native_mcp_log_tools)
nms_enable_sanitizers(native_mcp_log_tools)

add_library(native_mcp_protocol STATIC
  src/json_rpc.cpp
  src/server.cpp
)
add_library(native_mcp::protocol ALIAS native_mcp_protocol)
target_compile_features(native_mcp_protocol PUBLIC cxx_std_20)
target_include_directories(native_mcp_protocol
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_link_libraries(native_mcp_protocol
  PUBLIC native_mcp::foundation native_mcp::log_tools nlohmann_json::nlohmann_json
)
nms_set_project_warnings(native_mcp_protocol)
nms_enable_sanitizers(native_mcp_protocol)

add_executable(native-mcp-sandbox src/main.cpp)
target_link_libraries(native-mcp-sandbox PRIVATE native_mcp::protocol)
nms_set_project_warnings(native-mcp-sandbox)
nms_enable_sanitizers(native-mcp-sandbox)

if(BUILD_TESTING)
  add_executable(native_mcp_foundation_tests tests/foundation_tests.cpp)
  target_link_libraries(native_mcp_foundation_tests PRIVATE native_mcp::foundation)
  target_compile_features(native_mcp_foundation_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_foundation_tests)
  nms_enable_sanitizers(native_mcp_foundation_tests)

  add_executable(native_mcp_policy_tests tests/file_policy_tests.cpp)
  target_link_libraries(native_mcp_policy_tests
    PRIVATE native_mcp::policy nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_policy_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_policy_tests)
  nms_enable_sanitizers(native_mcp_policy_tests)

  add_executable(native_mcp_log_analysis_tests tests/log_analysis_tests.cpp)
  target_link_libraries(native_mcp_log_analysis_tests
    PRIVATE native_mcp::log_tools nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_log_analysis_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_log_analysis_tests)
  nms_enable_sanitizers(native_mcp_log_analysis_tests)

  add_executable(native_mcp_protocol_tests tests/protocol_tests.cpp)
  target_link_libraries(native_mcp_protocol_tests
    PRIVATE native_mcp::protocol nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_protocol_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_protocol_tests)
  nms_enable_sanitizers(native_mcp_protocol_tests)

  add_executable(native_mcp_stdio_integration_tests
    tests/stdio_integration_tests.cpp
  )
  target_link_libraries(native_mcp_stdio_integration_tests
    PRIVATE nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_stdio_integration_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_stdio_integration_tests)
  nms_enable_sanitizers(native_mcp_stdio_integration_tests)

  add_test(NAME foundation.unit COMMAND native_mcp_foundation_tests)
  add_test(NAME foundation.self_check COMMAND native-mcp-sandbox --self-check)
  add_test(NAME policy.unit COMMAND native_mcp_policy_tests)
  add_test(NAME logs.unit COMMAND native_mcp_log_analysis_tests)
  add_test(NAME protocol.unit COMMAND native_mcp_protocol_tests)
  add_test(
    NAME protocol.stdio_integration
    COMMAND native_mcp_stdio_integration_tests $<TARGET_FILE:native-mcp-sandbox>
  )
endif()

install(TARGETS native-mcp-sandbox RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
