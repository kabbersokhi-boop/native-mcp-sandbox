#include "native_mcp/json_rpc.hpp"
#include "native_mcp/server.hpp"

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>

namespace {

using native_mcp::LifecycleState;
using native_mcp::ProcessResult;
using native_mcp::Server;
using native_mcp::json_rpc::Json;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

Json response_json(const ProcessResult& result) {
  expect(result.response.has_value(), "expected a JSON-RPC response");
  return Json::parse(*result.response);
}

void expect_no_response(const ProcessResult& result,
                        const std::string_view message) {
  expect(!result.response.has_value(), message);
}

Json initialize(Server& server, const Json& id = 1) {
  const Json request{
      {"jsonrpc", "2.0"},
      {"id", id},
      {"method", "initialize"},
      {"params",
       Json{{"protocolVersion", "2025-11-25"},
            {"capabilities", Json::object()},
            {"clientInfo", Json{{"name", "test-client"}, {"version", "1.0"}}}}},
  };
  return response_json(server.process_line(request.dump()));
}

void become_ready(Server& server) {
  const Json initialized{{"jsonrpc", "2.0"},
                         {"method", "notifications/initialized"}};
  expect_no_response(server.process_line(initialized.dump()),
                     "initialized notification must not receive a response");
  expect(server.state() == LifecycleState::kReady,
         "initialized notification must enter ready state");
}

void test_parse_and_envelope_errors() {
  Server server;
  Json response = response_json(server.process_line("{"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kParseError,
         "malformed JSON must return parse error");
  expect(response["id"].is_null(), "parse error id must be null");

  response = response_json(server.process_line("[]"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidRequest,
         "top-level arrays must be rejected");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":1.5,"method":"ping"})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidRequest,
         "fractional ids must be rejected");
  expect(response["id"].is_null(), "invalid id errors must use null id");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":null,"method":"ping"})"));
  expect(response["id"].is_null(), "null ids must be preserved");
  expect(response.contains("result"), "null-id request must still be handled");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":"abc","method":"ping"})"));
  expect(response["id"] == "abc", "string ids must be preserved");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":-7,"method":"ping"})"));
  expect(response["id"].is_number_integer() && response["id"] == -7,
         "signed integer ids must be accepted");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":18446744073709551615,"method":"ping"})"));
  expect(response["id"].is_number_unsigned(),
         "unsigned integer ids must be accepted");
}

void test_notifications_and_unknown_methods() {
  Server server;
  ProcessResult result = server.process_line(
      R"({"jsonrpc":"2.0","method":"unknown/notification"})");
  expect_no_response(result, "unknown notifications must not receive responses");
  expect(result.diagnostic.has_value(),
         "unknown notifications should produce a safe diagnostic");

  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":9,"method":"unknown/request"})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kMethodNotFound,
         "unknown requests must return method not found");
}

void test_lifecycle() {
  Server server;

  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":1,"method":"ping"})"));
  expect(response["result"].is_object(), "ping must work before initialization");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":2,"method":"tools/list"})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kLifecycleError,
         "tools/list must fail before initialization completes");

  response = initialize(server, "init-1");
  expect(response["id"] == "init-1", "initialize id must be preserved");
  expect(response["result"]["protocolVersion"] == "2025-11-25",
         "initialize must negotiate the targeted protocol version");
  expect(response["result"]["capabilities"].contains("tools"),
         "initialize must advertise tool discovery capability");
  expect(response["result"]["serverInfo"]["version"] == "0.2.0",
         "initialize must report the Phase 1 version");
  expect(server.state() == LifecycleState::kAwaitingInitializedNotification,
         "initialize response must advance to awaiting notification");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":3,"method":"tools/list"})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kLifecycleError,
         "tools/list must wait for initialized notification");

  become_ready(server);
  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":4,"method":"tools/list","params":{}})"));
  expect(response["result"]["tools"].is_array(),
         "tools/list result must contain an array");
  expect(response["result"]["tools"].empty(),
         "Phase 1 tools/list must be intentionally empty");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":5,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"again","version":"1"}}})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kLifecycleError,
         "initialization must not be repeatable");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":6,"method":"ping"})"));
  expect(response.contains("result"), "ping must work after initialization");
}

void test_initialize_validation() {
  Server server;
  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"client","version":"1"}}})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
         "unsupported protocol versions must be rejected");
  expect(server.state() == LifecycleState::kUninitialized,
         "failed initialize must not advance state");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":2,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":[],"clientInfo":{"name":"client","version":"1"}}})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
         "client capabilities must be an object");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":3,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"","version":"1"}}})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
         "client name must be non-empty");
}

void test_response_limit_preserves_state() {
  auto budget = native_mcp::conservative_budget();
  budget.max_response_bytes = 100U;
  Server server{budget};
  const Json response = initialize(server);
  expect(response["error"]["code"] == native_mcp::json_rpc::kResponseTooLarge,
         "oversized initialize response must become a bounded error");
  expect(server.state() == LifecycleState::kUninitialized,
         "oversized initialize response must not advance lifecycle state");
}


void test_bounded_stdio_drains_oversized_lines() {
  auto budget = native_mcp::conservative_budget();
  budget.max_request_bytes = 64U;
  std::string oversized(256U, 'x');
  std::istringstream input{
      oversized + "\n{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"ping\"}\n"};
  std::ostringstream output;
  std::ostringstream diagnostics;
  expect(native_mcp::run_stdio(input, output, diagnostics, budget) == 0,
         "stdio loop must recover after an oversized line");

  std::istringstream responses{output.str()};
  std::string first_line;
  std::string second_line;
  expect(static_cast<bool>(std::getline(responses, first_line)),
         "oversized input must produce a size error");
  expect(static_cast<bool>(std::getline(responses, second_line)),
         "request after oversized input must still be processed");
  const Json first = Json::parse(first_line);
  const Json second = Json::parse(second_line);
  expect(first["error"]["code"] == native_mcp::json_rpc::kRequestTooLarge,
         "oversized line must return request-too-large");
  expect(second["id"] == 7 && second.contains("result"),
         "line reader must drain, reset, and preserve framing");
  expect(diagnostics.str().find(oversized) == std::string::npos,
         "diagnostics must not echo oversized untrusted input");
}

void test_request_size_error() {
  Server server;
  const Json response = response_json(server.request_too_large());
  expect(response["error"]["code"] == native_mcp::json_rpc::kRequestTooLarge,
         "oversized requests must return a structured size error");
}

}  // namespace

int main() {
  test_parse_and_envelope_errors();
  test_notifications_and_unknown_methods();
  test_lifecycle();
  test_initialize_validation();
  test_response_limit_preserves_state();
  test_request_size_error();
  test_bounded_stdio_drains_oversized_lines();
  std::cout << "All protocol tests passed\n";
  return EXIT_SUCCESS;
}
