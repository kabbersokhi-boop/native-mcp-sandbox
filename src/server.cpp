#include "native_mcp/server.hpp"

#include "native_mcp/json_rpc.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <istream>
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

[[nodiscard]] HandlerResult handle_tools_list(const Json& message,
                                              const Json& id,
                                              const LifecycleState state) {
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
  return HandlerResult{
      .response = json_rpc::make_result(id, Json{{"tools", Json::array()}}),
      .diagnostic = std::nullopt,
      .next_state = std::nullopt,
  };
}

[[nodiscard]] HandlerResult dispatch(const Json& message,
                                     const Json& id,
                                     const bool notification,
                                     const LifecycleState state) {
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
    return handle_tools_list(message, id, state);
  }

  if (notification) {
    return notification_diagnostic("ignored unsupported notification");
  }
  return request_error(id, json_rpc::kMethodNotFound, "Method not found");
}

[[nodiscard]] ProcessResult serialize_bounded(
    Json response,
    const ResourceBudget& budget,
    const std::optional<LifecycleState> next_state,
    LifecycleState& state) {
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
        .diagnostic = "replaced oversized response with uncorrelated bounded error",
    };
  }

  return ProcessResult{
      .response = std::nullopt,
      .diagnostic = "response limit too small for a JSON-RPC error",
  };
}

void write_diagnostic(std::ostream& diagnostics,
                      const std::optional<std::string>& message) {
  if (message.has_value()) {
    diagnostics << "native-mcp-sandbox: " << *message << '\n';
  }
}

[[nodiscard]] bool write_response(std::ostream& output,
                                  const std::optional<std::string>& response) {
  if (!response.has_value()) {
    return true;
  }
  output << *response << '\n';
  output.flush();
  return static_cast<bool>(output);
}

}  // namespace

Server::Server(const ResourceBudget budget) : budget_(budget) {
  if (!is_budget_valid(budget_)) {
    budget_ = conservative_budget();
  }
}

ProcessResult Server::process_line(const std::string_view line) {
  Json message = Json::parse(line, nullptr, false);
  if (message.is_discarded()) {
    return serialize_bounded(
        json_rpc::make_error(null_id(), json_rpc::kParseError, "Parse error"),
        budget_, std::nullopt, state_);
  }

  if (!message.is_object()) {
    return serialize_bounded(json_rpc::make_error(
                                 null_id(), json_rpc::kInvalidRequest,
                                 "Invalid Request"),
                             budget_, std::nullopt, state_);
  }

  const auto jsonrpc = message.find("jsonrpc");
  const auto method = message.find("method");
  const auto id = message.find("id");
  const bool has_id = id != message.end();
  const bool notification = !has_id;

  if (has_id && !json_rpc::is_valid_id(*id)) {
    return serialize_bounded(json_rpc::make_error(
                                 null_id(), json_rpc::kInvalidRequest,
                                 "Invalid Request"),
                             budget_, std::nullopt, state_);
  }

  if (jsonrpc == message.end() || !jsonrpc->is_string() ||
      jsonrpc->get_ref<const std::string&>() != "2.0" ||
      method == message.end() || !method->is_string()) {
    if (notification && method != message.end() && method->is_string()) {
      return ProcessResult{
          .response = std::nullopt,
          .diagnostic = "ignored malformed notification envelope",
      };
    }
    const Json response_id = has_id ? *id : null_id();
    return serialize_bounded(json_rpc::make_error(
                                 response_id, json_rpc::kInvalidRequest,
                                 "Invalid Request"),
                             budget_, std::nullopt, state_);
  }

  const Json request_id = has_id ? *id : null_id();
  HandlerResult handled = dispatch(message, request_id, notification, state_);
  if (!handled.response.has_value()) {
    if (handled.next_state.has_value()) {
      state_ = *handled.next_state;
    }
    return ProcessResult{.response = std::nullopt,
                         .diagnostic = std::move(handled.diagnostic)};
  }

  ProcessResult result = serialize_bounded(std::move(*handled.response), budget_,
                                           handled.next_state, state_);
  if (!result.diagnostic.has_value() && handled.diagnostic.has_value()) {
    result.diagnostic = std::move(handled.diagnostic);
  }
  return result;
}

ProcessResult Server::request_too_large() const {
  LifecycleState unchanged = state_;
  return serialize_bounded(
      json_rpc::make_error(null_id(), json_rpc::kRequestTooLarge,
                           "Request exceeds configured limit"),
      budget_, std::nullopt, unchanged);
}

LifecycleState Server::state() const noexcept { return state_; }

int run_stdio(std::istream& input,
              std::ostream& output,
              std::ostream& diagnostics,
              const ResourceBudget budget) {
  if (!is_budget_valid(budget)) {
    diagnostics << "native-mcp-sandbox: invalid resource budget\n";
    return 78;
  }

  Server server{budget};
  std::string line;
  line.reserve(std::min<std::size_t>(budget.max_request_bytes, 4U * 1024U));
  bool oversized = false;

  const auto process_current_line = [&]() -> bool {
    ProcessResult result;
    if (oversized) {
      result = server.request_too_large();
    } else {
      if (!line.empty() && line.back() == '\r') {
        line.pop_back();
      }
      result = server.process_line(line);
    }
    write_diagnostic(diagnostics, result.diagnostic);
    const bool success = write_response(output, result.response);
    line.clear();
    oversized = false;
    return success;
  };

  char character = '\0';
  while (input.get(character)) {
    if (character == '\n') {
      if (!process_current_line()) {
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
    diagnostics << "native-mcp-sandbox: failed to read protocol input\n";
    return 74;
  }

  if (oversized || !line.empty()) {
    if (!process_current_line()) {
      diagnostics << "native-mcp-sandbox: failed to write protocol response\n";
      return 74;
    }
  }

  return 0;
}

}  // namespace native_mcp
