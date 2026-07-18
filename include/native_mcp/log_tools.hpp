#pragma once

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

class LogToolService final {
 public:
  explicit LogToolService(FilesystemPolicy policy,
                          LogAnalysisLimits limits = {});

  LogToolService(const LogToolService&) = delete;
  LogToolService& operator=(const LogToolService&) = delete;
  LogToolService(LogToolService&&) noexcept = default;
  LogToolService& operator=(LogToolService&&) noexcept = default;

  [[nodiscard]] nlohmann::json tool_definitions() const;
  [[nodiscard]] bool knows_tool(std::string_view name) const noexcept;
  [[nodiscard]] ToolExecutionResult execute(
      std::string_view name, const nlohmann::json& arguments);

 private:
  [[nodiscard]] bool acquire_rate_limit_slot();

  FilesystemPolicy policy_;
  LogAnalyzer analyzer_;
  std::deque<std::chrono::steady_clock::time_point> recent_calls_;
};

}  // namespace native_mcp
