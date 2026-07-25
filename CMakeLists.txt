cmake_minimum_required(VERSION 3.20)

project(
  native_mcp_sandbox
  VERSION 0.10.0
  DESCRIPTION "A security-first, resource-bounded C++20 server for local MCP evidence tools"
  LANGUAGES CXX
)

include(CTest)
include(GNUInstallDirs)

set(NMS_GENERATED_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
configure_file(
  "${CMAKE_CURRENT_SOURCE_DIR}/cmake/native_mcp_version.hpp.in"
  "${NMS_GENERATED_INCLUDE_DIR}/native_mcp/version.hpp"
  @ONLY
)

find_package(Threads REQUIRED)

option(NMS_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(NMS_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(NMS_ENABLE_THREAD_SANITIZER "Enable ThreadSanitizer" OFF)
option(NMS_BUILD_FUZZERS "Build Clang libFuzzer targets" OFF)
option(NMS_BUILD_BENCHMARKS "Build bounded reproducibility benchmark targets" OFF)

if(NMS_ENABLE_SANITIZERS AND NMS_ENABLE_THREAD_SANITIZER)
  message(FATAL_ERROR "Address/UndefinedBehavior sanitizers cannot be combined with ThreadSanitizer")
endif()

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

function(nms_enable_thread_sanitizer target)
  if(NMS_ENABLE_THREAD_SANITIZER)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
      target_compile_options(${target} PRIVATE
        -fsanitize=thread -fno-omit-frame-pointer
      )
      target_link_options(${target} PRIVATE -fsanitize=thread)
    else()
      message(FATAL_ERROR "NMS_ENABLE_THREAD_SANITIZER requires GCC or Clang")
    endif()
  endif()
endfunction()

function(nms_enable_runtime_checks target)
  nms_enable_sanitizers(${target})
  nms_enable_thread_sanitizer(${target})
endfunction()

function(nms_enable_fuzzer_instrumentation target)
  if(NMS_BUILD_FUZZERS)
    if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
      target_compile_options(${target} PRIVATE -fsanitize=fuzzer-no-link)
    else()
      message(FATAL_ERROR "NMS_BUILD_FUZZERS requires Clang")
    endif()
  endif()
endfunction()

add_library(native_mcp_foundation STATIC
  src/foundation.cpp
  src/json_safety.cpp
)
add_library(native_mcp::foundation ALIAS native_mcp_foundation)
target_compile_features(native_mcp_foundation PUBLIC cxx_std_20)
target_include_directories(native_mcp_foundation
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_include_directories(native_mcp_foundation PRIVATE
  "${NMS_GENERATED_INCLUDE_DIR}"
)
target_link_libraries(native_mcp_foundation PUBLIC nlohmann_json::nlohmann_json)
nms_set_project_warnings(native_mcp_foundation)
nms_enable_runtime_checks(native_mcp_foundation)
nms_enable_fuzzer_instrumentation(native_mcp_foundation)

add_library(native_mcp_policy STATIC
  src/file_policy.cpp
  src/process_memory.cpp
  src/runtime_config.cpp
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
nms_enable_runtime_checks(native_mcp_policy)
nms_enable_fuzzer_instrumentation(native_mcp_policy)

add_library(native_mcp_tools STATIC
  src/log_analysis.cpp
  src/elf_analysis.cpp
  src/tool_service.cpp
)
add_library(native_mcp::tools ALIAS native_mcp_tools)
target_compile_features(native_mcp_tools PUBLIC cxx_std_20)
target_include_directories(native_mcp_tools
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_link_libraries(native_mcp_tools
  PUBLIC native_mcp::policy nlohmann_json::nlohmann_json
)
nms_set_project_warnings(native_mcp_tools)
nms_enable_runtime_checks(native_mcp_tools)
nms_enable_fuzzer_instrumentation(native_mcp_tools)

add_library(native_mcp_protocol STATIC
  src/json_rpc.cpp
  src/server.cpp
  src/orchestration.cpp
)
add_library(native_mcp::protocol ALIAS native_mcp_protocol)
target_compile_features(native_mcp_protocol PUBLIC cxx_std_20)
target_include_directories(native_mcp_protocol
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_link_libraries(native_mcp_protocol
  PUBLIC native_mcp::foundation native_mcp::tools nlohmann_json::nlohmann_json Threads::Threads
)
nms_set_project_warnings(native_mcp_protocol)
nms_enable_runtime_checks(native_mcp_protocol)
nms_enable_fuzzer_instrumentation(native_mcp_protocol)

if(BUILD_TESTING OR NMS_BUILD_FUZZERS)
  add_library(native_mcp_fuzz_support STATIC fuzz/fuzz_support.cpp)
  target_include_directories(native_mcp_fuzz_support PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/fuzz)
  target_link_libraries(native_mcp_fuzz_support PUBLIC native_mcp::protocol)
  target_compile_features(native_mcp_fuzz_support PUBLIC cxx_std_20)
  nms_set_project_warnings(native_mcp_fuzz_support)
  nms_enable_runtime_checks(native_mcp_fuzz_support)
nms_enable_fuzzer_instrumentation(native_mcp_fuzz_support)
endif()

add_executable(native-mcp-sandbox src/main.cpp)
target_link_libraries(native-mcp-sandbox PRIVATE native_mcp::protocol)
nms_set_project_warnings(native-mcp-sandbox)
nms_enable_runtime_checks(native-mcp-sandbox)

if(NMS_BUILD_BENCHMARKS)
  add_executable(native_mcp_bench benchmarks/native_mcp_bench.cpp)
  target_link_libraries(native_mcp_bench PRIVATE native_mcp::protocol nlohmann_json::nlohmann_json Threads::Threads)
  target_compile_features(native_mcp_bench PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_bench)
  nms_enable_runtime_checks(native_mcp_bench)
endif()

if(BUILD_TESTING)
  add_executable(native_mcp_foundation_tests tests/foundation_tests.cpp)
  target_link_libraries(native_mcp_foundation_tests PRIVATE native_mcp::foundation)
  target_compile_features(native_mcp_foundation_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_foundation_tests)
  nms_enable_runtime_checks(native_mcp_foundation_tests)

  add_executable(native_mcp_policy_tests tests/file_policy_tests.cpp)
  target_link_libraries(native_mcp_policy_tests
    PRIVATE native_mcp::policy nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_policy_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_policy_tests)
  nms_enable_runtime_checks(native_mcp_policy_tests)


  add_executable(native_mcp_process_memory_tests tests/process_memory_tests.cpp)
  target_link_libraries(native_mcp_process_memory_tests
    PRIVATE native_mcp::policy nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_process_memory_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_process_memory_tests)
  nms_enable_runtime_checks(native_mcp_process_memory_tests)

  add_executable(native_mcp_process_parsing_tests tests/process_parsing_tests.cpp)
  target_link_libraries(native_mcp_process_parsing_tests
    PRIVATE native_mcp::policy
  )
  target_compile_features(native_mcp_process_parsing_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_process_parsing_tests)
  nms_enable_runtime_checks(native_mcp_process_parsing_tests)

  add_executable(native_mcp_log_analysis_tests tests/log_analysis_tests.cpp)
  target_link_libraries(native_mcp_log_analysis_tests
    PRIVATE native_mcp::tools nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_log_analysis_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_log_analysis_tests)
  nms_enable_runtime_checks(native_mcp_log_analysis_tests)

  add_executable(native_mcp_elf_analysis_tests tests/elf_analysis_tests.cpp)
  target_link_libraries(native_mcp_elf_analysis_tests
    PRIVATE native_mcp::tools nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_elf_analysis_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_elf_analysis_tests)
  nms_enable_runtime_checks(native_mcp_elf_analysis_tests)


  add_executable(native_mcp_orchestration_tests tests/orchestration_tests.cpp)
  target_link_libraries(native_mcp_orchestration_tests
    PRIVATE native_mcp::protocol nlohmann_json::nlohmann_json Threads::Threads
  )
  target_compile_features(native_mcp_orchestration_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_orchestration_tests)
  nms_enable_runtime_checks(native_mcp_orchestration_tests)

  add_executable(native_mcp_protocol_tests tests/protocol_tests.cpp)
  target_link_libraries(native_mcp_protocol_tests
    PRIVATE native_mcp::protocol nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_protocol_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_protocol_tests)
  nms_enable_runtime_checks(native_mcp_protocol_tests)

  add_executable(native_mcp_stdio_integration_tests
    tests/stdio_integration_tests.cpp
  )
  target_link_libraries(native_mcp_stdio_integration_tests
    PRIVATE nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_stdio_integration_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_stdio_integration_tests)
  nms_enable_runtime_checks(native_mcp_stdio_integration_tests)

  add_executable(native_mcp_json_safety_tests tests/json_safety_tests.cpp)
  target_link_libraries(native_mcp_json_safety_tests
    PRIVATE native_mcp::foundation nlohmann_json::nlohmann_json
  )
  target_compile_features(native_mcp_json_safety_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_json_safety_tests)
  nms_enable_runtime_checks(native_mcp_json_safety_tests)

  add_executable(native_mcp_security_regression_tests
    tests/security_regression_tests.cpp
  )
  target_link_libraries(native_mcp_security_regression_tests
    PRIVATE native_mcp::protocol nlohmann_json::nlohmann_json Threads::Threads
  )
  target_compile_features(native_mcp_security_regression_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_security_regression_tests)
  nms_enable_runtime_checks(native_mcp_security_regression_tests)

  add_executable(native_mcp_orchestration_stress_tests
    tests/orchestration_stress_tests.cpp
  )
  target_link_libraries(native_mcp_orchestration_stress_tests
    PRIVATE native_mcp::protocol nlohmann_json::nlohmann_json Threads::Threads
  )
  target_compile_features(native_mcp_orchestration_stress_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_orchestration_stress_tests)
  nms_enable_runtime_checks(native_mcp_orchestration_stress_tests)

  add_executable(native_mcp_fuzz_smoke fuzz/fuzz_smoke.cpp)
  target_link_libraries(native_mcp_fuzz_smoke PRIVATE native_mcp_fuzz_support)
  target_compile_features(native_mcp_fuzz_smoke PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_fuzz_smoke)
  nms_enable_runtime_checks(native_mcp_fuzz_smoke)

  add_test(NAME foundation.unit COMMAND native_mcp_foundation_tests)
  add_test(
    NAME foundation.version_output
    COMMAND ${CMAKE_COMMAND}
            "-DNMS_EXECUTABLE=$<TARGET_FILE:native-mcp-sandbox>"
            "-DNMS_EXPECTED=native-mcp-sandbox ${PROJECT_VERSION}"
            -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/verify_version.cmake
  )
  add_test(NAME foundation.self_check COMMAND native-mcp-sandbox --self-check)
  add_test(NAME policy.unit COMMAND native_mcp_policy_tests)
  file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/test-tmp")
  set_tests_properties(policy.unit PROPERTIES
    ENVIRONMENT "NMS_TEST_TMPDIR=${CMAKE_CURRENT_BINARY_DIR}/test-tmp"
  )
  add_test(NAME process.unit COMMAND native_mcp_process_memory_tests)
  add_test(NAME process_parsing.unit COMMAND native_mcp_process_parsing_tests)
  add_test(NAME logs.unit COMMAND native_mcp_log_analysis_tests)
  add_test(NAME elf.unit COMMAND native_mcp_elf_analysis_tests)
  add_test(NAME orchestration.unit COMMAND native_mcp_orchestration_tests)
  add_test(NAME orchestration.stress COMMAND native_mcp_orchestration_stress_tests)
  add_test(NAME json_safety.unit COMMAND native_mcp_json_safety_tests)
  add_test(NAME security.regression COMMAND native_mcp_security_regression_tests)
  add_test(NAME security.fuzz_smoke COMMAND native_mcp_fuzz_smoke --iterations 1500)
  add_test(NAME protocol.unit COMMAND native_mcp_protocol_tests)
  add_test(
    NAME protocol.stdio_integration
    COMMAND native_mcp_stdio_integration_tests $<TARGET_FILE:native-mcp-sandbox>
  )
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(
    NAME agent.investigation_demo
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/agent_investigation_demo_test.py
            --server $<TARGET_FILE:native-mcp-sandbox>
  )
  set_tests_properties(agent.investigation_demo PROPERTIES TIMEOUT 90)
  if(NMS_BUILD_BENCHMARKS)
    add_test(
      NAME benchmarks.component_smoke
      COMMAND native_mcp_bench ${CMAKE_CURRENT_SOURCE_DIR}/benchmarks/fixtures
    )
    set_tests_properties(benchmarks.component_smoke PROPERTIES TIMEOUT 30)
    add_test(
      NAME benchmarks.failure_bounds
      COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/benchmark_failure_tests.py
    )
    set_tests_properties(benchmarks.failure_bounds PROPERTIES TIMEOUT 30)
  endif()
endif()

if(NMS_BUILD_FUZZERS)
  if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    message(FATAL_ERROR "NMS_BUILD_FUZZERS requires Clang")
  endif()
  if(NOT NMS_ENABLE_SANITIZERS)
    message(FATAL_ERROR "NMS_BUILD_FUZZERS requires NMS_ENABLE_SANITIZERS=ON")
  endif()

  function(nms_add_fuzzer target source)
    add_executable(${target} ${source})
    target_link_libraries(${target} PRIVATE native_mcp_fuzz_support)
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_compile_options(${target} PRIVATE -fsanitize=fuzzer)
    target_link_options(${target} PRIVATE -fsanitize=fuzzer)
    nms_set_project_warnings(${target})
    nms_enable_runtime_checks(${target})
  endfunction()

  nms_add_fuzzer(native_mcp_fuzz_protocol fuzz/fuzz_protocol.cpp)
  nms_add_fuzzer(native_mcp_fuzz_runtime_config fuzz/fuzz_runtime_config.cpp)
  nms_add_fuzzer(native_mcp_fuzz_elf fuzz/fuzz_elf.cpp)
  nms_add_fuzzer(native_mcp_fuzz_log fuzz/fuzz_log.cpp)
  nms_add_fuzzer(native_mcp_fuzz_process fuzz/fuzz_process.cpp)
endif()

install(TARGETS native-mcp-sandbox RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
