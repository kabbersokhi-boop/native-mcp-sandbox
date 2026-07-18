#include "native_mcp/foundation.hpp"

#include <sstream>

namespace native_mcp {

bool is_budget_valid(const ResourceBudget& budget) noexcept {
  constexpr std::size_t kHardMessageLimit = 16U * 1024U * 1024U;
  constexpr std::size_t kHardQueueLimit = 1'024U;
  constexpr std::size_t kHardWorkerLimit = 64U;
  constexpr std::uint32_t kHardTimeoutMs = 300'000U;

  return budget.max_request_bytes > 0U &&
         budget.max_request_bytes <= kHardMessageLimit &&
         budget.max_response_bytes > 0U &&
         budget.max_response_bytes <= kHardMessageLimit &&
         budget.max_pending_requests > 0U &&
         budget.max_pending_requests <= kHardQueueLimit &&
         budget.worker_threads > 0U &&
         budget.worker_threads <= kHardWorkerLimit &&
         budget.operation_timeout_ms > 0U &&
         budget.operation_timeout_ms <= kHardTimeoutMs;
}

std::string budget_summary(const ResourceBudget& budget) {
  std::ostringstream output;
  output << "request_limit=" << budget.max_request_bytes
         << " response_limit=" << budget.max_response_bytes
         << " queue_limit=" << budget.max_pending_requests
         << " workers=" << budget.worker_threads
         << " timeout_ms=" << budget.operation_timeout_ms;
  return output.str();
}

std::string_view project_name() noexcept { return "native-mcp-sandbox"; }

std::string_view project_version() noexcept { return "0.4.0"; }

}  // namespace native_mcp
