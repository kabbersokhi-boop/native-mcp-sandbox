#include "native_mcp/foundation.hpp"
#include "native_mcp/json_rpc.hpp"
#include "native_mcp/orchestration.hpp"
#include "native_mcp/runtime_config.hpp"
#include "native_mcp/server.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>

namespace {

using namespace std::chrono_literals;
using Json = nlohmann::json;
using native_mcp::OperationContext;
using native_mcp::ResourceBudget;
using native_mcp::ScheduledToolCall;
using native_mcp::Server;
using native_mcp::ToolExecutionResult;
using native_mcp::ToolScheduler;
using native_mcp::ToolSubmitStatus;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

[[nodiscard]] Json response_json(const native_mcp::ProcessResult& result) {
  expect(result.response.has_value(), "expected a JSON-RPC response");
  const Json parsed = Json::parse(*result.response, nullptr, false);
  expect(!parsed.is_discarded(), "response must be valid JSON");
  return parsed;
}

void test_hostile_json_is_rejected_without_echo() {
  Server server;
  const std::string duplicate =
      R"({"jsonrpc":"2.0","id":1,"method":"ping","method":"SECRET"})";
  const Json duplicate_response = response_json(server.process_line(duplicate));
  expect(duplicate_response["error"]["code"] ==
             native_mcp::json_rpc::kInvalidRequest,
         "duplicate protocol keys must be an invalid request");
  expect(duplicate_response.dump().find("SECRET") == std::string::npos,
         "rejected request material must not be echoed");

  std::string deep_params(65U, '[');
  deep_params += "null";
  deep_params.append(65U, ']');
  const std::string deep =
      R"({"jsonrpc":"2.0","id":2,"method":"ping","params":)" +
      deep_params + "}";
  const Json deep_response = response_json(server.process_line(deep));
  expect(deep_response["error"]["code"] ==
             native_mcp::json_rpc::kInvalidRequest,
         "excessively nested protocol JSON must fail closed");

  std::string invalid_utf8 =
      R"({"jsonrpc":"2.0","id":3,"method":"ping","params":{"x":")";
  invalid_utf8.push_back(static_cast<char>(0xff));
  invalid_utf8 += R"("}})";
  const Json invalid_response = response_json(server.process_line(invalid_utf8));
  expect(invalid_response["error"]["code"] ==
             native_mcp::json_rpc::kParseError,
         "invalid UTF-8 must remain a parse error");

  std::string token_bomb =
      R"({"jsonrpc":"2.0","id":4,"method":"ping","params":{"values":[)";
  for (std::size_t index = 0U; index < 33U * 1024U; ++index) {
    if (index != 0U) {
      token_bomb.push_back(',');
    }
    token_bomb.push_back('0');
  }
  token_bomb += "]}}";
  const Json token_response = response_json(server.process_line(token_bomb));
  expect(token_response["error"]["code"] ==
             native_mcp::json_rpc::kInvalidRequest,
         "protocol token bombs must be rejected before DOM construction");
}

void test_hostile_configs_are_rejected() {
  const auto duplicate = native_mcp::parse_runtime_policy_config(
      R"({"version":1,"version":2,"roots":[],"processes":[{"name":"self","pid":"self"}]})");
  expect(!duplicate.config.has_value() && duplicate.error.has_value(),
         "duplicate runtime-policy keys must be rejected");

  std::string deep(33U, '[');
  deep += "0";
  deep.append(33U, ']');
  const auto nested = native_mcp::parse_runtime_policy_config(
      R"({"version":2,"roots":[],"processes":)" + deep + "}");
  expect(!nested.config.has_value() && nested.error.has_value(),
         "deep runtime-policy JSON must be rejected before DOM parsing");
}

void test_oversized_stdio_line_is_bounded() {
  ResourceBudget budget = native_mcp::conservative_budget();
  budget.max_request_bytes = 128U;
  budget.max_response_bytes = 512U;
  std::string oversized(1024U, 'x');

  Server direct{budget};
  const Json direct_response = response_json(direct.process_line(oversized));
  expect(direct_response["error"]["code"] ==
             native_mcp::json_rpc::kRequestTooLarge,
         "direct server use must enforce the request byte budget");

  oversized.push_back('\n');
  std::istringstream input{oversized};
  std::ostringstream output;
  std::ostringstream diagnostics;
  const int status =
      native_mcp::run_stdio(input, output, diagnostics, budget, std::nullopt);
  expect(status == 0, "oversized input must produce a bounded protocol response");
  expect(output.str().size() <= budget.max_response_bytes + 1U,
         "oversized request response must respect the configured limit");
  expect(output.str().find(std::string(32U, 'x')) == std::string::npos,
         "oversized input must not be reflected into stdout");
}

void test_numeric_request_ids_are_canonical() {
  std::mutex mutex;
  std::condition_variable cv;
  bool release = false;
  ToolScheduler scheduler{
      ResourceBudget{.max_request_bytes = 4096U,
                     .max_response_bytes = 4096U,
                     .max_pending_requests = 2U,
                     .worker_threads = 1U,
                     .operation_timeout_ms = 1000U},
      [&](std::string_view, const Json&, const OperationContext&) {
        std::unique_lock lock{mutex};
        cv.wait(lock, [&] { return release; });
        return ToolExecutionResult{.is_error = false,
                                   .structured_content = Json::object()};
      },
      [](const Json&, ToolExecutionResult) {}};

  const Json signed_id = Json::number_integer_t{7};
  const Json unsigned_id = Json::number_unsigned_t{7U};
  expect(scheduler.submit(ScheduledToolCall{signed_id, "test", Json::object()}) ==
             ToolSubmitStatus::kAccepted,
         "first numeric request id must be accepted");
  expect(scheduler.submit(
             ScheduledToolCall{unsigned_id, "test", Json::object()}) ==
             ToolSubmitStatus::kDuplicateRequestId,
         "equal signed and unsigned JSON-RPC ids must be treated as duplicates");
  {
    std::lock_guard lock{mutex};
    release = true;
  }
  cv.notify_all();
  scheduler.shutdown();
}

}  // namespace

int main() {
  test_hostile_json_is_rejected_without_echo();
  test_hostile_configs_are_rejected();
  test_oversized_stdio_line_is_bounded();
  test_numeric_request_ids_are_canonical();
  std::cout << "All security regression tests passed\n";
  return EXIT_SUCCESS;
}
