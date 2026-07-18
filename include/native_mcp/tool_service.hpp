#pragma once

#include "native_mcp/elf_analysis.hpp"
#include "native_mcp/file_policy.hpp"
#include "native_mcp/log_analysis.hpp"
#include "native_mcp/operation.hpp"
#include "native_mcp/process_memory.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <deque>
#include <memory>
#include <optional>
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
  ToolService(std::optional<FilesystemPolicy> filesystem_policy,
              std::optional<ProcessPolicy> process_policy,
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
  [[nodiscard]] ToolExecutionResult execute(
      std::string_view name, const nlohmann::json& arguments,
      const OperationContext& context);

 private:
  struct RateState;

  [[nodiscard]] bool acquire_rate_limit_slot();

  std::optional<FilesystemPolicy> filesystem_policy_;
  std::optional<ProcessPolicy> process_policy_;
  LogAnalyzer log_analyzer_;
  ElfAnalyzer elf_analyzer_;
  std::shared_ptr<RateState> rate_state_;
};

}  // namespace native_mcp
