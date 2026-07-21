#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
build_dir=${NMS_FUZZ_BUILD_DIR:-"${root_dir}/build/fuzz"}
artifact_dir=${NMS_FUZZ_ARTIFACT_DIR:-"${root_dir}/build/fuzz-artifacts"}
seconds=${NMS_FUZZ_SECONDS:-60}

if ! [[ ${seconds} =~ ^[0-9]+$ ]] || [[ ${seconds} -lt 1 ]]; then
  echo "NMS_FUZZ_SECONDS must be a positive integer" >&2
  exit 64
fi

mkdir -p "${artifact_dir}"
export CXX=${CXX:-clang++}
export ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=1:abort_on_error=1:strict_string_checks=1:check_initialization_order=1}
export UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1:print_stacktrace=1}

cmake -S "${root_dir}" -B "${build_dir}" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DBUILD_TESTING=ON \
  -DNMS_WARNINGS_AS_ERRORS=ON \
  -DNMS_ENABLE_SANITIZERS=ON \
  -DNMS_BUILD_FUZZERS=ON
cmake --build "${build_dir}" --parallel 2

run_target() {
  local target=$1
  local corpus=$2
  local dictionary=$3
  local max_length=$4
  local target_artifacts="${artifact_dir}/${target}"
  local working_corpus="${artifact_dir}/corpus/${target}"
  rm -rf "${working_corpus}"
  mkdir -p "${target_artifacts}" "${working_corpus}"
  cp -a "${corpus}/." "${working_corpus}/"

  "${build_dir}/${target}" "${working_corpus}" \
    -runs=0 \
    -timeout=10 \
    -rss_limit_mb=2048 \
    -max_len="${max_length}" \
    -dict="${dictionary}" \
    -artifact_prefix="${target_artifacts}/"

  "${build_dir}/${target}" "${working_corpus}" \
    -max_total_time="${seconds}" \
    -timeout=10 \
    -rss_limit_mb=2048 \
    -max_len="${max_length}" \
    -dict="${dictionary}" \
    -artifact_prefix="${target_artifacts}/" \
    -print_final_stats=1
}

run_target native_mcp_fuzz_protocol \
  "${root_dir}/fuzz/corpus/protocol" \
  "${root_dir}/fuzz/dictionaries/json.dict" 1048576
run_target native_mcp_fuzz_runtime_config \
  "${root_dir}/fuzz/corpus/runtime_config" \
  "${root_dir}/fuzz/dictionaries/json.dict" 65536
run_target native_mcp_fuzz_elf \
  "${root_dir}/fuzz/corpus/elf" \
  "${root_dir}/fuzz/dictionaries/elf.dict" 1048576
run_target native_mcp_fuzz_log \
  "${root_dir}/fuzz/corpus/log" \
  "${root_dir}/fuzz/dictionaries/log.dict" 262144
run_target native_mcp_fuzz_process \
  "${root_dir}/fuzz/corpus/process" \
  "${root_dir}/fuzz/dictionaries/process.dict" 262144

echo "fuzz campaign completed; artifacts: ${artifact_dir}"
