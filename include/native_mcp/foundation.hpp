#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace native_mcp {

struct ResourceBudget final {
  std::size_t max_request_bytes;
  std::size_t max_response_bytes;
  std::size_t max_pending_requests;
  std::size_t worker_threads;
  std::uint32_t operation_timeout_ms;
};

[[nodiscard]] constexpr ResourceBudget conservative_budget() noexcept {
  return ResourceBudget{
      .max_request_bytes = 1U * 1024U * 1024U,
      .max_response_bytes = 1U * 1024U * 1024U,
      .max_pending_requests = 16U,
      .worker_threads = 2U,
      .operation_timeout_ms = 30'000U,
  };
}

[[nodiscard]] bool is_budget_valid(const ResourceBudget& budget) noexcept;
[[nodiscard]] std::string budget_summary(const ResourceBudget& budget);
[[nodiscard]] std::string_view project_name() noexcept;
[[nodiscard]] std::string_view project_version() noexcept;

}  // namespace native_mcp

