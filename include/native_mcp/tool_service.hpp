#pragma once

#include "native_mcp/elf_analysis.hpp"
#include "native_mcp/file_policy.hpp"
#include "native_mcp/log_analysis.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <deque>
#include <string_view>

namespace native_mcp {

struct ToolExecutionResult final {
  bool is_error;
  nlohmann::json structured_content;
};

class ToolService final {
 public:
  explicit ToolService(FilesystemPolicy policy,
                       LogAnalysisLimits log_limits = {},
                       ElfInspectionLimits elf_limits = {});

  ToolService(const ToolService&) = delete;
  ToolService& operator=(const ToolService&) = delete;
  ToolService(ToolService&&) noexcept = default;
  ToolService& operator=(ToolService&&) noexcept = default;

  [[nodiscard]] nlohmann::json tool_definitions() const;
  [[nodiscard]] bool knows_tool(std::string_view name) const noexcept;
  [[nodiscard]] ToolExecutionResult execute(
      std::string_view name, const nlohmann::json& arguments);

 private:
  [[nodiscard]] bool acquire_rate_limit_slot();

  FilesystemPolicy policy_;
  LogAnalyzer log_analyzer_;
  ElfAnalyzer elf_analyzer_;
  std::deque<std::chrono::steady_clock::time_point> recent_calls_;
};

}  // namespace native_mcp
