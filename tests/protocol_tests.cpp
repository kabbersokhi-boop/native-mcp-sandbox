#include "native_mcp/file_policy.hpp"
#include "native_mcp/process_memory.hpp"

#include <elf.h>
#include "native_mcp/json_rpc.hpp"
#include "native_mcp/tool_service.hpp"
#include "native_mcp/server.hpp"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

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

void write_minimal_elf64(const fs::path& path) {
  std::vector<unsigned char> bytes(64U, 0U);
  bytes[EI_MAG0] = ELFMAG0;
  bytes[EI_MAG1] = ELFMAG1;
  bytes[EI_MAG2] = ELFMAG2;
  bytes[EI_MAG3] = ELFMAG3;
  bytes[EI_CLASS] = ELFCLASS64;
  bytes[EI_DATA] = ELFDATA2LSB;
  bytes[EI_VERSION] = EV_CURRENT;
  bytes[EI_OSABI] = ELFOSABI_LINUX;
  bytes[16U] = static_cast<unsigned char>(ET_EXEC);
  bytes[18U] = static_cast<unsigned char>(EM_X86_64);
  bytes[20U] = static_cast<unsigned char>(EV_CURRENT);
  bytes[52U] = 64U;
  bytes[54U] = 56U;
  std::ofstream output(path, std::ios::binary);
  output.write(reinterpret_cast<const char*>(bytes.data()),
               static_cast<std::streamsize>(bytes.size()));
}

Json response_json(const ProcessResult& result) {
  expect(result.response.has_value(), "expected a JSON-RPC response");
  return Json::parse(*result.response);
}

Json tool_text_json(const Json& response) {
  return Json::parse(response["result"]["content"][0]["text"].get<std::string>());
}

void expect_closed_output_schema(const Json& schema) {
  expect(schema.is_object(), "output schema nodes must be objects");
  const Json& type = schema.at("type");
  const bool is_object =
      (type.is_string() && type == "object") ||
      (type.is_array() && std::any_of(type.begin(), type.end(),
                                      [](const Json& value) {
                                        return value == "object";
                                      }));
  if (is_object) {
    expect(schema.contains("additionalProperties") &&
               schema["additionalProperties"] == false,
           "native output object schemas must explicitly be closed");
  }
  if (const auto properties = schema.find("properties");
      properties != schema.end()) {
    expect(properties->is_object(), "output properties must be an object");
    for (const auto& [unused, property] : properties->items()) {
      (void)unused;
      expect_closed_output_schema(property);
    }
  }
  if (const auto items = schema.find("items"); items != schema.end()) {
    expect_closed_output_schema(*items);
  }
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
  std::optional<native_mcp::ToolService> tools;
  tools.emplace(std::move(*created.policy));
  return Server{native_mcp::conservative_budget(), std::move(tools)};
}

Server process_configured_server() {
  native_mcp::ProcessPolicyConfig config;
  config.processes.push_back({.name = "server", .pid = std::nullopt});
  native_mcp::ProcessPolicyLimits limits;
  limits.allow_legacy_process_pinning = true;
  auto created = native_mcp::ProcessPolicy::create(config, limits);
  expect(created.policy.has_value(), "test process policy must be created");
  std::optional<native_mcp::ToolService> tools;
  tools.emplace(std::nullopt,
                std::optional<native_mcp::ProcessPolicy>{std::move(*created.policy)});
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
  expect(response["error"]["code"] ==
             native_mcp::json_rpc::kInvalidRequest,
         "null request ids must be rejected");
  expect(response["id"].is_null(), "null-id errors must use null id");

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

void test_cancellation_notifications() {
  Server server;

  auto action = server.accept_line(
      R"({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":"work-1","reason":"no longer needed"}})");
  expect(action.cancellation.has_value() &&
             action.cancellation->request_id == "work-1" &&
             !action.immediate.has_value(),
         "valid cancellation notifications must expose the target request id");

  action = server.accept_line(
      R"({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1.5}})");
  expect(action.immediate.has_value() &&
             !action.immediate->response.has_value() &&
             action.immediate->diagnostic.has_value(),
         "malformed cancellation notifications must be ignored safely");

  action = server.accept_line(
      R"({"jsonrpc":"2.0","id":2,"method":"notifications/cancelled","params":{"requestId":1}})");
  expect(action.immediate.has_value(),
         "cancellation requests must receive an invalid-request response");
  const Json response = response_json(*action.immediate);
  expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidRequest,
         "notifications/cancelled must remain notification-only");
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
  expect(response["result"]["serverInfo"]["version"] == "0.11.0",
         "initialize must report the planned v0.11.0 version");
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
  write_minimal_elf64(directory.path() / "sample.elf");
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
  expect(tools.size() == 3U, "configured server must advertise the three bounded tools");
  expect(tools[0]["name"] == "logs.search" &&
             tools[1]["name"] == "logs.tail" &&
             tools[2]["name"] == "elf.inspect",
         "tool names must be stable and deterministic");
  expect(tools[0]["annotations"]["readOnlyHint"] == true &&
             tools[0]["execution"]["taskSupport"] == "forbidden",
         "tool metadata must declare read-only synchronous behavior");
  for (const Json& tool : tools) {
    expect_closed_output_schema(tool["outputSchema"]);
  }

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
      R"({"jsonrpc":"2.0","id":40,"method":"tools/call","params":{"name":"elf.inspect","arguments":{"root":"logs","path":"sample.elf"}}})"));
  expect(response["result"]["isError"] == false &&
             response["result"]["structuredContent"]["class"] == "ELF64" &&
             response["result"]["structuredContent"]["machine"] == "x86_64" &&
             response["result"]["structuredContent"]["interpreter"].is_null() &&
             response["result"]["structuredContent"]["buildId"].is_null(),
         "approved ELF inspection must return schema-valid bounded metadata");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":41,"method":"tools/call","params":{"name":"elf.inspect","arguments":{"root":"logs","path":"app.log"}}})"));
  expect(response["result"]["isError"] == true &&
             !response["result"].contains("structuredContent") &&
             tool_text_json(response)["error"]["code"] == "invalid_elf",
         "non-ELF targets must return a schema-safe tool execution error");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":42,"method":"tools/call","params":{"name":"elf.inspect","arguments":{"root":"logs","path":"sample.elf","extra":true}}})"));
  expect(response["result"]["isError"] == true &&
             tool_text_json(response)["error"]["code"] == "invalid_arguments",
         "ELF tool arguments must use a closed schema");

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

void test_process_memory_tool_protocol() {
  Server server = process_configured_server();
  (void)initialize(server);
  become_ready(server);

  Json response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":50,"method":"tools/list"})"));
  const Json& tools = response["result"]["tools"];
  expect(tools.size() == 1U && tools[0]["name"] == "proc.memory",
         "process-only configuration must advertise only proc.memory");
  expect(tools[0]["annotations"]["readOnlyHint"] == true &&
             tools[0]["execution"]["taskSupport"] == "forbidden",
         "process observation must be advertised as read-only and synchronous");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":51,"method":"tools/call","params":{"name":"proc.memory","arguments":{"process":"server"}}})"));
  expect(response["result"]["isError"] == false &&
             response["result"]["structuredContent"]["pid"] > 0U &&
             response["result"]["structuredContent"]["status"]["vmRssBytes"].is_number_unsigned(),
         "proc.memory must return bounded aggregate memory counters");
  expect(response["result"]["structuredContent"] == tool_text_json(response),
         "process text content must mirror structured content");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":52,"method":"tools/call","params":{"name":"proc.memory","arguments":{"process":"missing"}}})"));
  expect(response["result"]["isError"] == true &&
             !response["result"].contains("structuredContent") &&
             tool_text_json(response)["error"]["code"] == "unknown_process",
         "unknown process aliases must produce bounded tool errors");

  response = response_json(server.process_line(
      R"({"jsonrpc":"2.0","id":53,"method":"tools/call","params":{"name":"proc.memory","arguments":{"process":"server","pid":1}}})"));
  expect(response["result"]["isError"] == true &&
             tool_text_json(response)["error"]["code"] == "invalid_arguments",
         "proc.memory must reject undeclared fields and raw PID selection");
}

void test_initialize_validation() {
  {
    Server server;
    const Json response = response_json(server.process_line(
        R"({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"client","version":"1"}}})"));
    expect(response["result"]["protocolVersion"] == "2025-11-25",
           "the server must negotiate by returning its supported revision");
    expect(server.state() == LifecycleState::kAwaitingInitializedNotification,
           "a negotiated initialize response must advance lifecycle state");
  }

  {
    Server server;
    const Json response = response_json(server.process_line(
        R"({"jsonrpc":"2.0","id":2,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":[],"clientInfo":{"name":"client","version":"1"}}})"));
    expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
           "client capabilities must be an object");
    expect(server.state() == LifecycleState::kUninitialized,
           "invalid capabilities must not advance lifecycle state");
  }

  {
    Server server;
    const Json response = response_json(server.process_line(
        R"({"jsonrpc":"2.0","id":3,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"","version":"1"}}})"));
    expect(response["error"]["code"] == native_mcp::json_rpc::kInvalidParams,
           "client name must be non-empty");
    expect(server.state() == LifecycleState::kUninitialized,
           "invalid client information must not advance lifecycle state");
  }
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
  test_cancellation_notifications();
  test_lifecycle();
  test_log_tool_protocol();
  test_process_memory_tool_protocol();
  test_initialize_validation();
  test_response_limit_preserves_state();
  test_request_size_error();
  test_bounded_stdio_drains_oversized_lines();
  std::cout << "All protocol tests passed\n";
  return EXIT_SUCCESS;
}
