#include "native_mcp/server.hpp"

#include "native_mcp/json_rpc.hpp"
#include "native_mcp/orchestration.hpp"

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <istream>
#include <memory>
#include <mutex>
#include <ostream>
#include <string>
#include <utility>

namespace native_mcp {
namespace {

using json_rpc::Json;

constexpr std::string_view kProtocolVersion = "2025-11-25";
constexpr std::string_view kServerName = "native-mcp-sandbox";

struct HandlerResult final {
  std::optional<Json> response;
  std::optional<std::string> diagnostic;
  std::optional<LifecycleState> next_state;
};

struct ToolCallPreparation final {
  std::optional<PreparedToolCall> call;
  std::optional<HandlerResult> error;
};

[[nodiscard]] Json null_id() { return nullptr; }

[[nodiscard]] bool valid_optional_object_params(const Json& message) {
  const auto params = message.find("params");
  return params == message.end() || params->is_object();
}

[[nodiscard]] bool valid_nonempty_string_member(const Json& object,
                                                const char* key) {
  const auto member = object.find(key);
  return member != object.end() && member->is_string() &&
         !member->get_ref<const std::string&>().empty();
}

[[nodiscard]] HandlerResult request_error(const Json& id,
                                          const std::int32_t code,
                                          const std::string_view message) {
  return HandlerResult{
      .response = json_rpc::make_error(id, code, message),
      .diagnostic = std::nullopt,
      .next_state = std::nullopt,
  };
}

[[nodiscard]] HandlerResult notification_diagnostic(std::string message) {
  return HandlerResult{
      .response = std::nullopt,
      .diagnostic = std::move(message),
      .next_state = std::nullopt,
  };
}

[[nodiscard]] HandlerResult handle_initialize(const Json& message,
                                              const Json& id,
                                              const LifecycleState state) {
  if (state != LifecycleState::kUninitialized) {
    return request_error(id, json_rpc::kLifecycleError,
                         "Initialization has already started");
  }

  const auto params = message.find("params");
  if (params == message.end() || !params->is_object()) {
    return request_error(id, json_rpc::kInvalidParams,
                         "initialize requires object params");
  }

  const auto protocol_version = params->find("protocolVersion");
  const auto capabilities = params->find("capabilities");
  const auto client_info = params->find("clientInfo");
  if (protocol_version == params->end() || !protocol_version->is_string() ||
      capabilities == params->end() || !capabilities->is_object() ||
      client_info == params->end() || !client_info->is_object() ||
      !valid_nonempty_string_member(*client_info, "name") ||
      !valid_nonempty_string_member(*client_info, "version")) {
    return request_error(id, json_rpc::kInvalidParams,
                         "Invalid initialize parameters");
  }

  const auto& requested = protocol_version->get_ref<const std::string&>();
  if (requested != kProtocolVersion) {
    Json data{{"requested", requested},
              {"supported", Json::array({kProtocolVersion})}};
    return HandlerResult{
        .response = json_rpc::make_error(id, json_rpc::kInvalidParams,
                                         "Unsupported protocol version",
                                         std::move(data)),
        .diagnostic = std::nullopt,
        .next_state = std::nullopt,
    };
  }

  Json result{
      {"protocolVersion", kProtocolVersion},
      {"capabilities", Json{{"tools", Json::object()}}},
      {"serverInfo",
       Json{{"name", kServerName}, {"version", project_version()}}},
  };
  return HandlerResult{
      .response = json_rpc::make_result(id, std::move(result)),
      .diagnostic = std::nullopt,
      .next_state = LifecycleState::kAwaitingInitializedNotification,
  };
}

[[nodiscard]] HandlerResult handle_tools_list(
    const Json& message, const Json& id, const LifecycleState state,
    ToolService* tools) {
  if (state != LifecycleState::kReady) {
    return request_error(id, json_rpc::kLifecycleError,
                         "Server is not ready for tool discovery");
  }
  if (!valid_optional_object_params(message)) {
    return request_error(id, json_rpc::kInvalidParams,
                         "tools/list params must be an object");
  }
  const auto params = message.find("params");
  if (params != message.end()) {
    const auto cursor = params->find("cursor");
    if (cursor != params->end() && !cursor->is_string()) {
      return request_error(id, json_rpc::kInvalidParams,
                           "tools/list cursor must be a string");
    }
  }
  Json definitions = tools == nullptr ? Json::array() : tools->tool_definitions();
  return HandlerResult{
      .response =
          json_rpc::make_result(id, Json{{"tools", std::move(definitions)}}),
      .diagnostic = std::nullopt,
      .next_state = std::nullopt,
  };
}

[[nodiscard]] ToolCallPreparation prepare_tools_call(
    const Json& message, const Json& id, const LifecycleState state,
    ToolService* tools) {
  if (state != LifecycleState::kReady) {
    return {.call = std::nullopt,
            .error = request_error(id, json_rpc::kLifecycleError,
                                   "Server is not ready for tool calls")};
  }
  const auto params = message.find("params");
  if (params == message.end() || !params->is_object()) {
    return {.call = std::nullopt,
            .error = request_error(id, json_rpc::kInvalidParams,
                                   "tools/call requires object params")};
  }
  if (params->contains("task")) {
    return {.call = std::nullopt,
            .error = request_error(
                id, json_rpc::kInvalidParams,
                "Task-augmented tool execution is not supported")};
  }
  const auto name = params->find("name");
  if (name == params->end() || !name->is_string() ||
      name->get_ref<const std::string&>().empty()) {
    return {.call = std::nullopt,
            .error = request_error(id, json_rpc::kInvalidParams,
                                   "tools/call requires a nonempty tool name")};
  }
  const auto arguments = params->find("arguments");
  if (arguments != params->end() && !arguments->is_object()) {
    return {.call = std::nullopt,
            .error = request_error(id, json_rpc::kInvalidParams,
                                   "tools/call arguments must be an object")};
  }

  const auto& tool_name = name->get_ref<const std::string&>();
  if (tools == nullptr || !tools->knows_tool(tool_name)) {
    return {.call = std::nullopt,
            .error = request_error(id, json_rpc::kInvalidParams,
                                   "Unknown tool")};
  }
  return {.call = PreparedToolCall{
              .request_id = id,
              .name = tool_name,
              .arguments = arguments == params->end() ? Json::object()
                                                       : *arguments,
          },
          .error = std::nullopt};
}

[[nodiscard]] HandlerResult dispatch(const Json& message, const Json& id,
                                     const bool notification,
                                     const LifecycleState state,
                                     ToolService* tools) {
  const auto& method = message.at("method").get_ref<const std::string&>();

  if (method == "ping") {
    if (!valid_optional_object_params(message)) {
      if (notification) {
        return notification_diagnostic(
            "ignored ping notification with invalid params");
      }
      return request_error(id, json_rpc::kInvalidParams,
                           "ping params must be an object");
    }
    if (notification) {
      return notification_diagnostic("ignored ping notification");
    }
    return HandlerResult{
        .response = json_rpc::make_result(id, Json::object()),
        .diagnostic = std::nullopt,
        .next_state = std::nullopt,
    };
  }

  if (method == "initialize") {
    if (notification) {
      return notification_diagnostic("ignored initialize notification");
    }
    return handle_initialize(message, id, state);
  }

  if (method == "notifications/initialized") {
    if (!notification) {
      return request_error(id, json_rpc::kInvalidRequest,
                           "notifications/initialized must be a notification");
    }
    if (!valid_optional_object_params(message)) {
      return notification_diagnostic(
          "ignored initialized notification with invalid params");
    }
    if (state != LifecycleState::kAwaitingInitializedNotification) {
      return notification_diagnostic(
          "ignored initialized notification in invalid lifecycle state");
    }
    return HandlerResult{
        .response = std::nullopt,
        .diagnostic = std::nullopt,
        .next_state = LifecycleState::kReady,
    };
  }

  if (method == "tools/list") {
    if (notification) {
      return notification_diagnostic("ignored tools/list notification");
    }
    return handle_tools_list(message, id, state, tools);
  }

  if (method == "tools/call" && notification) {
    return notification_diagnostic("ignored tools/call notification");
  }

  if (notification) {
    return notification_diagnostic("ignored unsupported notification");
  }
  return request_error(id, json_rpc::kMethodNotFound, "Method not found");
}

[[nodiscard]] ProcessResult serialize_bounded(
    Json response, const ResourceBudget& budget,
    const std::optional<LifecycleState> next_state, LifecycleState& state) {
  std::string serialized = response.dump();
  if (serialized.size() <= budget.max_response_bytes) {
    if (next_state.has_value()) {
      state = *next_state;
    }
    return ProcessResult{.response = std::move(serialized),
                         .diagnostic = std::nullopt};
  }

  Json response_id = null_id();
  const auto id = response.find("id");
  if (id != response.end() && json_rpc::is_valid_id(*id)) {
    response_id = *id;
  }

  Json fallback = json_rpc::make_error(response_id,
                                       json_rpc::kResponseTooLarge,
                                       "Response exceeds configured limit");
  serialized = fallback.dump();
  if (serialized.size() <= budget.max_response_bytes) {
    return ProcessResult{
        .response = std::move(serialized),
        .diagnostic = "replaced oversized response with bounded error",
    };
  }

  fallback = json_rpc::make_error(null_id(), json_rpc::kResponseTooLarge,
                                  "Response exceeds configured limit");
  serialized = fallback.dump();
  if (serialized.size() <= budget.max_response_bytes) {
    return ProcessResult{
        .response = std::move(serialized),
        .diagnostic =
            "replaced oversized response with uncorrelated bounded error",
    };
  }

  return ProcessResult{
      .response = std::nullopt,
      .diagnostic = "response limit too small for a JSON-RPC error",
  };
}

[[nodiscard]] ToolExecutionResult tool_error_execution(
    const std::string_view code, const std::string_view message) {
  return ToolExecutionResult{
      .is_error = true,
      .structured_content =
          Json{{"error", Json{{"code", code}, {"message", message}}}},
  };
}

class SerializedProtocolWriter final {
 public:
  SerializedProtocolWriter(std::ostream& output, std::ostream& diagnostics)
      : output_(output), diagnostics_(diagnostics) {}

  [[nodiscard]] bool write(const ProcessResult& result) {
    std::lock_guard lock{mutex_};
    if (failed_.load(std::memory_order_acquire)) {
      return false;
    }
    if (result.diagnostic.has_value()) {
      diagnostics_ << "native-mcp-sandbox: " << *result.diagnostic << '\n';
    }
    if (result.response.has_value()) {
      output_ << *result.response << '\n';
      output_.flush();
      if (!output_) {
        failed_.store(true, std::memory_order_release);
        return false;
      }
    }
    if (!diagnostics_) {
      failed_.store(true, std::memory_order_release);
      return false;
    }
    return true;
  }

  [[nodiscard]] bool failed() const noexcept {
    return failed_.load(std::memory_order_acquire);
  }

 private:
  std::ostream& output_;
  std::ostream& diagnostics_;
  mutable std::mutex mutex_;
  std::atomic<bool> failed_{false};
};

}  // namespace

Server::Server(const ResourceBudget budget, std::optional<ToolService> tools)
    : Server(budget, tools.has_value()
                         ? std::make_shared<ToolService>(std::move(*tools))
                         : std::shared_ptr<ToolService>{}) {}

Server::Server(const ResourceBudget budget, std::shared_ptr<ToolService> tools)
    : budget_(budget), tools_(std::move(tools)) {
  if (!is_budget_valid(budget_)) {
    budget_ = conservative_budget();
  }
}

LineAction Server::accept_line(const std::string_view line) {
  Json message = Json::parse(line, nullptr, false);
  if (message.is_discarded()) {
    return {.immediate = serialize_bounded(
                json_rpc::make_error(null_id(), json_rpc::kParseError,
                                     "Parse error"),
                budget_, std::nullopt, state_)};
  }

  if (!message.is_object()) {
    return {.immediate = serialize_bounded(
                json_rpc::make_error(null_id(), json_rpc::kInvalidRequest,
                                     "Invalid Request"),
                budget_, std::nullopt, state_)};
  }

  const auto jsonrpc = message.find("jsonrpc");
  const auto method = message.find("method");
  const auto id = message.find("id");
  const bool has_id = id != message.end();
  const bool notification = !has_id;

  if (has_id && !json_rpc::is_valid_id(*id)) {
    return {.immediate = serialize_bounded(
                json_rpc::make_error(null_id(), json_rpc::kInvalidRequest,
                                     "Invalid Request"),
                budget_, std::nullopt, state_)};
  }

  if (jsonrpc == message.end() || !jsonrpc->is_string() ||
      jsonrpc->get_ref<const std::string&>() != "2.0" ||
      method == message.end() || !method->is_string()) {
    if (notification && method != message.end() && method->is_string()) {
      return {.immediate = ProcessResult{
                  .response = std::nullopt,
                  .diagnostic = "ignored malformed notification envelope",
              }};
    }
    const Json response_id = has_id ? *id : null_id();
    return {.immediate = serialize_bounded(
                json_rpc::make_error(response_id, json_rpc::kInvalidRequest,
                                     "Invalid Request"),
                budget_, std::nullopt, state_)};
  }

  const Json request_id = has_id ? *id : null_id();
  const auto& method_name = method->get_ref<const std::string&>();

  if (method_name == "tools/call" && !notification) {
    ToolCallPreparation prepared = prepare_tools_call(
        message, request_id, state_, tools_.get());
    if (prepared.error.has_value()) {
      HandlerResult handled = std::move(*prepared.error);
      return {.immediate = serialize_bounded(
                  std::move(*handled.response), budget_, handled.next_state,
                  state_)};
    }
    return {.tool_call = std::move(prepared.call)};
  }

  if (method_name == "notifications/cancelled") {
    if (!notification) {
      return {.immediate = serialize_bounded(
                  json_rpc::make_error(
                      request_id, json_rpc::kInvalidRequest,
                      "notifications/cancelled must be a notification"),
                  budget_, std::nullopt, state_)};
    }
    const auto params = message.find("params");
    if (params == message.end() || !params->is_object()) {
      return {.immediate = ProcessResult{
                  .response = std::nullopt,
                  .diagnostic =
                      "ignored cancellation notification with invalid params",
              }};
    }
    const auto cancelled_id = params->find("requestId");
    const auto reason = params->find("reason");
    if (cancelled_id == params->end() ||
        !json_rpc::is_valid_id(*cancelled_id) ||
        (reason != params->end() && !reason->is_string())) {
      return {.immediate = ProcessResult{
                  .response = std::nullopt,
                  .diagnostic =
                      "ignored malformed cancellation notification",
              }};
    }
    return {.cancellation = CancellationNotice{.request_id = *cancelled_id}};
  }

  HandlerResult handled = dispatch(message, request_id, notification, state_,
                                   tools_.get());
  if (!handled.response.has_value()) {
    if (handled.next_state.has_value()) {
      state_ = *handled.next_state;
    }
    return {.immediate = ProcessResult{
                .response = std::nullopt,
                .diagnostic = std::move(handled.diagnostic),
            }};
  }

  ProcessResult result = serialize_bounded(std::move(*handled.response), budget_,
                                           handled.next_state, state_);
  if (!result.diagnostic.has_value() && handled.diagnostic.has_value()) {
    result.diagnostic = std::move(handled.diagnostic);
  }
  return {.immediate = std::move(result)};
}

ProcessResult Server::process_line(const std::string_view line) {
  LineAction action = accept_line(line);
  if (action.immediate.has_value()) {
    return std::move(*action.immediate);
  }
  if (action.cancellation.has_value()) {
    return {.response = std::nullopt, .diagnostic = std::nullopt};
  }
  if (!action.tool_call.has_value() || tools_ == nullptr) {
    return {.response = std::nullopt,
            .diagnostic = "tool request could not be executed"};
  }
  PreparedToolCall call = std::move(*action.tool_call);
  return format_tool_result(
      call.request_id, tools_->execute(call.name, call.arguments));
}

ProcessResult Server::format_tool_result(
    const Json& request_id, ToolExecutionResult execution) const {
  const std::string text = execution.structured_content.dump();
  Json result{{"content", Json::array({Json{{"type", "text"},
                                             {"text", text}}})},
              {"isError", execution.is_error}};
  if (!execution.is_error) {
    result["structuredContent"] = std::move(execution.structured_content);
  }
  LifecycleState unchanged = LifecycleState::kReady;
  return serialize_bounded(
      json_rpc::make_result(request_id, std::move(result)), budget_,
      std::nullopt, unchanged);
}

ProcessResult Server::format_tool_error(
    const Json& request_id, const std::string_view code,
    const std::string_view message) const {
  return format_tool_result(request_id, tool_error_execution(code, message));
}

ProcessResult Server::request_too_large() const {
  LifecycleState unchanged = LifecycleState::kReady;
  return serialize_bounded(
      json_rpc::make_error(null_id(), json_rpc::kRequestTooLarge,
                           "Request exceeds configured limit"),
      budget_, std::nullopt, unchanged);
}

LifecycleState Server::state() const noexcept { return state_; }

std::shared_ptr<ToolService> Server::tool_service() const noexcept {
  return tools_;
}

int run_stdio(std::istream& input, std::ostream& output,
              std::ostream& diagnostics, const ResourceBudget budget,
              std::optional<ToolService> tools) {
  if (!is_budget_valid(budget)) {
    diagnostics << "native-mcp-sandbox: invalid resource budget\n";
    return 78;
  }

  std::shared_ptr<ToolService> shared_tools;
  if (tools.has_value()) {
    shared_tools = std::make_shared<ToolService>(std::move(*tools));
  }
  Server server{budget, shared_tools};
  SerializedProtocolWriter writer{output, diagnostics};

  std::unique_ptr<ToolScheduler> scheduler;
  if (shared_tools != nullptr) {
    scheduler = std::make_unique<ToolScheduler>(
        budget, shared_tools,
        [&server, &writer](const Json& request_id,
                           ToolExecutionResult execution) {
          (void)writer.write(
              server.format_tool_result(request_id, std::move(execution)));
        });
  }

  std::string line;
  line.reserve(std::min<std::size_t>(budget.max_request_bytes, 4U * 1024U));
  bool oversized = false;

  const auto process_action = [&](LineAction action) -> bool {
    if (action.immediate.has_value()) {
      return writer.write(*action.immediate);
    }
    if (action.cancellation.has_value()) {
      if (scheduler != nullptr) {
        (void)scheduler->cancel(action.cancellation->request_id);
      }
      return !writer.failed();
    }
    if (!action.tool_call.has_value() || scheduler == nullptr) {
      return writer.write(ProcessResult{
          .response = std::nullopt,
          .diagnostic = "tool request could not be scheduled",
      });
    }

    PreparedToolCall call = std::move(*action.tool_call);
    const Json request_id = call.request_id;
    const ToolSubmitStatus submitted = scheduler->submit(ScheduledToolCall{
        .request_id = std::move(call.request_id),
        .name = std::move(call.name),
        .arguments = std::move(call.arguments),
    });
    switch (submitted) {
      case ToolSubmitStatus::kAccepted:
        return !writer.failed();
      case ToolSubmitStatus::kQueueFull:
        return writer.write(server.format_tool_error(
            request_id, "server_busy",
            "bounded tool queue is full; retry after pending work completes"));
      case ToolSubmitStatus::kDuplicateRequestId:
        return writer.write(server.format_tool_error(
            request_id, "duplicate_request_id",
            "a tool request with this id is already in flight"));
      case ToolSubmitStatus::kStopped:
        return writer.write(server.format_tool_error(
            request_id, "server_stopping",
            "tool scheduler is no longer accepting work"));
    }
    return false;
  };

  const auto process_current_line = [&]() -> bool {
    LineAction action;
    if (oversized) {
      action.immediate = server.request_too_large();
    } else {
      if (!line.empty() && line.back() == '\r') {
        line.pop_back();
      }
      action = server.accept_line(line);
    }
    const bool success = process_action(std::move(action));
    line.clear();
    oversized = false;
    return success;
  };

  char character = '\0';
  while (input.get(character)) {
    if (character == '\n') {
      if (!process_current_line()) {
        if (scheduler != nullptr) {
          scheduler->shutdown();
        }
        diagnostics << "native-mcp-sandbox: failed to write protocol response\n";
        return 74;
      }
      continue;
    }

    if (oversized) {
      continue;
    }
    if (line.size() >= budget.max_request_bytes) {
      oversized = true;
      continue;
    }
    line.push_back(character);
  }

  if (input.bad()) {
    if (scheduler != nullptr) {
      scheduler->shutdown();
    }
    diagnostics << "native-mcp-sandbox: failed to read protocol input\n";
    return 74;
  }

  if (oversized || !line.empty()) {
    if (!process_current_line()) {
      if (scheduler != nullptr) {
        scheduler->shutdown();
      }
      diagnostics << "native-mcp-sandbox: failed to write protocol response\n";
      return 74;
    }
  }

  if (scheduler != nullptr) {
    scheduler->shutdown();
  }
  if (writer.failed()) {
    diagnostics << "native-mcp-sandbox: failed to write protocol response\n";
    return 74;
  }
  return 0;
}

}  // namespace native_mcp
