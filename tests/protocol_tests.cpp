#include "native_mcp/file_policy.hpp"
#include "native_mcp/json_rpc.hpp"
#include "native_mcp/log_tools.hpp"
#include "native_mcp/server.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace {

namespace fs = std::filesystem;
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

class TempDirectory final {
 public:
  TempDirectory() {
    std::string pattern = "/tmp/native-mcp-protocol-XXXXXX";
    pattern.push_back('\0');
    char* created = ::mkdtemp(pattern.data());
    expect(created != nullptr, "failed to create temporary directory");
    path_ = created;
  }
  ~TempDirectory() {
    std::error_code ignored;
    fs::remove_all(path_, ignored);
  }
  TempDirectory(const TempDirectory&) = delete;
  TempDirectory& operator=(const TempDirectory&) = delete;
  [[nodiscard]] const fs::path& path() const noexcept { return path_; }

 private:
  fs::path path_;
};

Json response_json(const ProcessResult& result) {
  expect(result.response.has_value(), "expected a JSON-RPC response");
  return Json::parse(*result.response);
}

Json tool_text_json(const Json& response) {
  return Json::parse(response["result"]["content"][0]["text"].get<std::string>());
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
            {"clientInfo", Json{{"name", "test-client"},
                                {"version", "1.0"}}}}},
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

Server configured_server(const fs::path& root) {
  native_mcp::FilesystemPolicyConfig config;
  config.roots.push_back(
      {.name = "logs", .path = root.string(), .max_file_bytes = 1024U * 1024U});
  native_mcp::FilesystemPolicyLimits limits;
  limits.allow_legacy_descriptor_walk = true;
  auto created = native_mcp::FilesystemPolicy::create(config, limits);
  expect(created.policy.has_value(), "test filesystem policy must be created");
  std::optional<native_mcp::LogToolService> tools;
  tools.emplace(std::move(*created.policy));
  return Server{native_mcp::conservative_budget(), std::move(tools)};
}

void test_parse_and_envelope_errors() {
  Server server;
  Json response = response_json(server.process_line("{"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kParseError,
         "malformed JSON must return parse error");
  expect(response["id"].is_null(), "parse error id must be null");

  response = response_json(server.process_line("[]"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kInvalidRequest,
         "top-level arrays must be rejected");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":1.5,"method":"ping"})"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kInvalidRequest,
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
  expect_no_response(result,
                     "unknown notifications must not receive responses");
  expect(result.diagnostic.has_value(),
         "unknown notifications should produce a safe diagnostic");

  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":9,"method":"unknown/request"})"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kMethodNotFound,
         "unknown requests must return method not found");
}

void test_lifecycle() {
  Server server;

  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":1,"method":"ping"})"));
  expect(response["result"].is_object(),
         "ping must work before initialization");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":2,"method":"tools/list"})"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kLifecycleError,
         "tools/list must fail before initialization completes");

  response = initialize(server, "init-1");
  expect(response["id"] == "init-1", "initialize id must be preserved");
  expect(response["result"]["protocolVersion"] == "2025-11-25",
         "initialize must negotiate the targeted protocol version");
  expect(response["result"]["capabilities"].contains("tools"),
         "initialize must advertise tool discovery capability");
  expect(response["result"]["serverInfo"]["version"] == "0.4.0",
         "initialize must report the Phase 3 version");
  expect(server.state() == LifecycleState::kAwaitingInitializedNotification,
         "initialize response must advance to awaiting notification");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":3,"method":"tools/list"})"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kLifecycleError,
         "tools/list must wait for initialized notification");

  become_ready(server);
  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":4,"method":"tools/list","params":{}})"));
  expect(response["result"]["tools"].is_array(),
         "tools/list result must contain an array");
  expect(response["result"]["tools"].empty(),
         "unconfigured server mode must expose no host tools");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":5,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"again","version":"1"}}})"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kLifecycleError,
         "initialization must not be repeatable");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":6,"method":"ping"})"));
  expect(response.contains("result"),
         "ping must work after initialization");
}

void test_log_tool_protocol() {
  TempDirectory directory;
  {
    std::ofstream output(directory.path() / "app.log");
    output << "INFO start\nERROR first\nINFO end\n";
  }
  Server server = configured_server(directory.path());

  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"logs.search","arguments":{}}})"));
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kLifecycleError,
         "tool calls must be rejected before lifecycle readiness");

  (void)initialize(server);
  become_ready(server);
  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":2,"method":"tools/list"})"));
  const Json& tools = response["result"]["tools"];
  expect(tools.size() == 2U, "configured server must advertise two log tools");
  expect(tools[0]["name"] == "logs.search" &&
             tools[1]["name"] == "logs.tail",
         "tool names must be stable and deterministic");
  expect(tools[0]["annotations"]["readOnlyHint"] == true &&
             tools[0]["execution"]["taskSupport"] == "forbidden",
         "tool metadata must declare read-only synchronous behavior");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"logs.search","arguments":{"root":"logs","path":"app.log","query":"error","caseSensitive":false,"maxMatches":5}}})"));
  expect(response["result"]["isError"] == false,
         "approved log search must succeed");
  expect(response["result"]["structuredContent"]["matches"].size() == 1U &&
             response["result"]["structuredContent"]["matches"][0]["line"] == 2U,
         "tool result must contain the matching line");
  const Json text_copy = Json::parse(
      response["result"]["content"][0]["text"].get<std::string>());
  expect(text_copy == response["result"]["structuredContent"],
         "text content must mirror structured content for compatibility");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"logs.tail","arguments":{"root":"logs","path":"app.log","maxLines":2}}})"));
  expect(response["result"]["isError"] == false &&
             response["result"]["structuredContent"]["lines"].size() == 2U,
         "approved log tail must return bounded final lines");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"logs.search","arguments":{"root":"logs","path":"../escape","query":"x"}}})"));
  expect(response["result"]["isError"] == true &&
             !response["result"].contains("structuredContent") &&
             tool_text_json(response)["error"]["code"] == "invalid_relative_path",
         "policy denials must be visible as schema-safe tool execution errors");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"logs.search","arguments":{"root":"logs","path":"app.log","query":"x","extra":true}}})"));
  expect(response["result"]["isError"] == true &&
             !response["result"].contains("structuredContent") &&
             tool_text_json(response)["error"]["code"] == "invalid_arguments",
         "tool arguments must use a closed schema");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"unknown.tool","arguments":{}}})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
         "unknown tools must produce a protocol-level invalid-params error");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"logs.tail","task":{"ttl":60000},"arguments":{"root":"logs","path":"app.log"}}})"));
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
         "task-augmented calls must be rejected when task support is forbidden");

  for (std::uint64_t id = 100U; id < 116U; ++id) {
    response = response_json(server.process_line(
        Json{{"jsonrpc", "2.0"},
             {"id", id},
             {"method", "tools/call"},
             {"params", Json{{"name", "logs.tail"},
                              {"arguments", Json{{"root", "logs"},
                                                 {"path", "app.log"},
                                                 {"maxLines", 1}}}}}}
            .dump()));
  }
  expect(response["result"]["isError"] == true &&
             tool_text_json(response)["error"]["code"] == "rate_limited",
         "rapid repeated tool calls must be rate limited");

  ProcessResult notification = server.process_line(
      R"({"jsonrpc":"2.0","method":"tools/call","params":{"name":"logs.tail","arguments":{"root":"logs","path":"app.log"}}})");
  expect_no_response(notification,
                     "tools/call notifications must never receive a response");
  expect(notification.diagnostic.has_value(),
         "ignored tools/call notifications should be diagnosed safely");
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
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kResponseTooLarge,
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
  test_log_tool_protocol();
  test_initialize_validation();
  test_response_limit_preserves_state();
  test_request_size_error();
  test_bounded_stdio_drains_oversized_lines();
  std::cout << "All protocol tests passed\n";
  return EXIT_SUCCESS;
}
