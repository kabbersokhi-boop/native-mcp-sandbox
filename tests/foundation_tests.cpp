#include "native_mcp/foundation.hpp"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

void expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(EXIT_FAILURE);
  }
}

}  // namespace

int main() {
  const auto budget = native_mcp::conservative_budget();
  expect(native_mcp::is_budget_valid(budget), "default budget must be valid");
  expect(budget.worker_threads == 2U, "default worker count must suit low-memory hosts");

  auto invalid = budget;
  invalid.worker_threads = 0U;
  expect(!native_mcp::is_budget_valid(invalid), "zero workers must be rejected");

  invalid = budget;
  invalid.max_request_bytes = 17U * 1024U * 1024U;
  expect(!native_mcp::is_budget_valid(invalid), "oversized request limit must be rejected");

  invalid = budget;
  invalid.operation_timeout_ms = 0U;
  expect(!native_mcp::is_budget_valid(invalid), "zero timeout must be rejected");

  const std::string summary = native_mcp::budget_summary(budget);
  expect(summary.find("workers=2") != std::string::npos, "summary must report worker count");
  expect(native_mcp::project_version() == "0.6.0", "version must match Phase 5 candidate");

  std::cout << "All foundation tests passed\n";
  return EXIT_SUCCESS;
}
