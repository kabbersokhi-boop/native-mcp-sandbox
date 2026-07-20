#pragma once

#include "native_mcp/process_memory.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace native_mcp::process_parsing {

struct ParsedIdentity final {
  std::string name;
  std::string state;
  std::uint64_t start_time_ticks = 0U;
};

struct ParsedStatus final {
  std::string name;
  std::string state;
  std::uint32_t effective_uid = 0U;
  std::uint64_t threads = 0U;
  ProcessStatusMemory memory;
};

[[nodiscard]] std::optional<ParsedIdentity> parse_stat_identity_text(
    std::string_view text);
[[nodiscard]] std::optional<ParsedStatus> parse_status_text(
    std::string_view text);
[[nodiscard]] std::optional<ProcessStatmMemory> parse_statm_text(
    std::string_view text, std::uint64_t page_size);
[[nodiscard]] std::optional<ProcessSmapsRollup> parse_smaps_rollup_text(
    std::string_view text);

}  // namespace native_mcp::process_parsing
