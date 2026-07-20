#pragma once

#include <cstdint>
#include <span>

namespace native_mcp::fuzzing {

void exercise_json_and_protocol(std::span<const std::uint8_t> input);
void exercise_runtime_config(std::span<const std::uint8_t> input);
void exercise_elf(std::span<const std::uint8_t> input);
void exercise_log(std::span<const std::uint8_t> input);
void exercise_process(std::span<const std::uint8_t> input);

}  // namespace native_mcp::fuzzing
