cmake_minimum_required(VERSION 3.20)

project(
  native_mcp_sandbox
  VERSION 0.1.0
  DESCRIPTION "A security-first, resource-bounded C++20 foundation for local MCP analysis tools"
  LANGUAGES CXX
)

include(CTest)
include(GNUInstallDirs)

option(NMS_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(NMS_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

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

add_executable(native-mcp-sandbox src/main.cpp)
target_link_libraries(native-mcp-sandbox PRIVATE native_mcp::foundation)

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

nms_set_project_warnings(native_mcp_foundation)
nms_set_project_warnings(native-mcp-sandbox)

if(NMS_ENABLE_SANITIZERS)
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    foreach(target native_mcp_foundation native-mcp-sandbox)
      target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
      target_link_options(${target} PRIVATE -fsanitize=address,undefined)
    endforeach()
  else()
    message(FATAL_ERROR "NMS_ENABLE_SANITIZERS requires GCC or Clang")
  endif()
endif()

if(BUILD_TESTING)
  add_executable(native_mcp_foundation_tests tests/foundation_tests.cpp)
  target_link_libraries(native_mcp_foundation_tests PRIVATE native_mcp::foundation)
  target_compile_features(native_mcp_foundation_tests PRIVATE cxx_std_20)
  nms_set_project_warnings(native_mcp_foundation_tests)

  if(NMS_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(native_mcp_foundation_tests PRIVATE
      -fsanitize=address,undefined -fno-omit-frame-pointer
    )
    target_link_options(native_mcp_foundation_tests PRIVATE -fsanitize=address,undefined)
  endif()

  add_test(NAME foundation.unit COMMAND native_mcp_foundation_tests)
  add_test(NAME foundation.self_check COMMAND native-mcp-sandbox --self-check)
endif()

install(TARGETS native-mcp-sandbox RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
