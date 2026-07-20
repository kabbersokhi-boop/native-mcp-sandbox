#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
iterations=${NMS_STRESS_ITERATIONS:-20000}

if ! [[ ${iterations} =~ ^[0-9]+$ ]] || [[ ${iterations} -lt 1 ]]; then
  echo "NMS_STRESS_ITERATIONS must be a positive integer" >&2
  exit 64
fi

asan_build=${NMS_ASAN_BUILD_DIR:-"${root_dir}/build/security-asan"}
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=1:abort_on_error=1:strict_string_checks=1} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1:print_stacktrace=1} \
CXX=${CXX_ASAN:-clang++} \
cmake -S "${root_dir}" -B "${asan_build}" -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DBUILD_TESTING=ON \
  -DNMS_WARNINGS_AS_ERRORS=ON \
  -DNMS_ENABLE_SANITIZERS=ON
cmake --build "${asan_build}" --parallel 2
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=1:abort_on_error=1:strict_string_checks=1} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1:print_stacktrace=1} \
ctest --test-dir "${asan_build}" --output-on-failure
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=1:abort_on_error=1:strict_string_checks=1} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1:print_stacktrace=1} \
"${asan_build}/native_mcp_fuzz_smoke" --iterations "${iterations}" --seed 828927513140

tsan_build=${NMS_TSAN_BUILD_DIR:-"${root_dir}/build/security-tsan"}
CXX=${CXX_TSAN:-g++} \
cmake -S "${root_dir}" -B "${tsan_build}" -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DBUILD_TESTING=ON \
  -DNMS_WARNINGS_AS_ERRORS=ON \
  -DNMS_ENABLE_THREAD_SANITIZER=ON
cmake --build "${tsan_build}" --target native_mcp_orchestration_tests native_mcp_orchestration_stress_tests --parallel 2
TSAN_OPTIONS=${TSAN_OPTIONS:-halt_on_error=1:second_deadlock_stack=1} \
ctest --test-dir "${tsan_build}" --output-on-failure \
  -R '^orchestration\.(unit|stress)$'

echo "native security stress suite completed"
