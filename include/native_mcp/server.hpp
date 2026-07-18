#pragma once

#include "native_mcp/foundation.hpp"
#include "native_mcp/tool_service.hpp"

#include <iosfwd>
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

class Server final {
 public:
  explicit Server(ResourceBudget budget = conservative_budget(),
                  std::optional<ToolService> tools = std::nullopt);

  [[nodiscard]] ProcessResult process_line(std::string_view line);
  [[nodiscard]] ProcessResult request_too_large() const;
  [[nodiscard]] LifecycleState state() const noexcept;

 private:
  ResourceBudget budget_;
  LifecycleState state_{LifecycleState::kUninitialized};
  std::optional<ToolService> tools_;
};

[[nodiscard]] int run_stdio(
    std::istream& input, std::ostream& output, std::ostream& diagnostics,
    ResourceBudget budget = conservative_budget(),
    std::optional<ToolService> tools = std::nullopt);

}  // namespace native_mcp
