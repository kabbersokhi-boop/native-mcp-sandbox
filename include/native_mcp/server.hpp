#pragma once

#include "native_mcp/foundation.hpp"
#include "native_mcp/tool_service.hpp"

#include <nlohmann/json.hpp>

#include <iosfwd>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

namespace native_mcp {

enum class LifecycleState {
  kUninitialized,
  kAwaitingInitializedNotification,
  kReady,
};

struct ProcessResult final {
  std::optional<std::string> response;
  std::optional<std::string> diagnostic;
};

struct PreparedToolCall final {
  nlohmann::json request_id;
  std::string name;
  nlohmann::json arguments;
};

struct CancellationNotice final {
  nlohmann::json request_id;
};

struct LineAction final {
  std::optional<ProcessResult> immediate{};
  std::optional<PreparedToolCall> tool_call{};
  std::optional<CancellationNotice> cancellation{};
};

class Server final {
 public:
  explicit Server(ResourceBudget budget = conservative_budget(),
                  std::optional<ToolService> tools = std::nullopt);
  Server(ResourceBudget budget, std::shared_ptr<ToolService> tools);

  [[nodiscard]] ProcessResult process_line(std::string_view line);
  [[nodiscard]] LineAction accept_line(std::string_view line);
  [[nodiscard]] ProcessResult format_tool_result(
      const nlohmann::json& request_id, ToolExecutionResult execution) const;
  [[nodiscard]] ProcessResult format_tool_error(
      const nlohmann::json& request_id, std::string_view code,
      std::string_view message) const;
  [[nodiscard]] ProcessResult request_too_large() const;
  [[nodiscard]] LifecycleState state() const noexcept;
  [[nodiscard]] std::shared_ptr<ToolService> tool_service() const noexcept;

 private:
  ResourceBudget budget_;
  LifecycleState state_{LifecycleState::kUninitialized};
  std::shared_ptr<ToolService> tools_;
};

[[nodiscard]] int run_stdio(
    std::istream& input, std::ostream& output, std::ostream& diagnostics,
    ResourceBudget budget = conservative_budget(),
    std::optional<ToolService> tools = std::nullopt);

}  // namespace native_mcp
