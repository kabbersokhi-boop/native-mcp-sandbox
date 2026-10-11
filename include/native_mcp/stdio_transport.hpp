#pragma once

#include <chrono>
#include <optional>

#include "native_mcp/foundation.hpp"
#include "native_mcp/tool_service.hpp"

namespace native_mcp {

[[nodiscard]] int run_native_stdio(ResourceBudget budget = conservative_budget(),
                                   std::optional<ToolService> tools = std::nullopt,
                                   std::chrono::milliseconds write_timeout = std::chrono::seconds{
                                       2});

}  // namespace native_mcp
