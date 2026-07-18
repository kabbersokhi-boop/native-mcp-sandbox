#include "native_mcp/json_rpc.hpp"

#include <utility>

namespace native_mcp::json_rpc {

static_assert(NLOHMANN_JSON_VERSION_MAJOR > 3 ||
                  (NLOHMANN_JSON_VERSION_MAJOR == 3 &&
                   NLOHMANN_JSON_VERSION_MINOR >= 11),
              "Native MCP Sandbox requires nlohmann/json 3.11 or newer");

bool is_valid_id(const Json& id) noexcept {
  return id.is_null() || id.is_string() || id.is_number_integer() ||
         id.is_number_unsigned();
}

Json make_result(const Json& id, Json result) {
  return Json{{"jsonrpc", "2.0"}, {"id", id}, {"result", std::move(result)}};
}

Json make_error(const Json& id,
                const std::int32_t code,
                const std::string_view message) {
  return Json{{"jsonrpc", "2.0"},
              {"id", id},
              {"error", Json{{"code", code}, {"message", message}}}};
}

Json make_error(const Json& id,
                const std::int32_t code,
                const std::string_view message,
                Json data) {
  return Json{{"jsonrpc", "2.0"},
              {"id", id},
              {"error",
               Json{{"code", code},
                    {"message", message},
                    {"data", std::move(data)}}}};
}

}  // namespace native_mcp::json_rpc
