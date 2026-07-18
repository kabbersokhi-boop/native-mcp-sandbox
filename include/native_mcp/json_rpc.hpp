#pragma once

#include <nlohmann/json.hpp>

#include <cstdint>
#include <string_view>

namespace native_mcp::json_rpc {

using Json = nlohmann::json;

inline constexpr std::int32_t kParseError = -32700;
inline constexpr std::int32_t kInvalidRequest = -32600;
inline constexpr std::int32_t kMethodNotFound = -32601;
inline constexpr std::int32_t kInvalidParams = -32602;
inline constexpr std::int32_t kInternalError = -32603;
inline constexpr std::int32_t kRequestTooLarge = -32001;
inline constexpr std::int32_t kLifecycleError = -32002;
inline constexpr std::int32_t kResponseTooLarge = -32003;

[[nodiscard]] bool is_valid_id(const Json& id) noexcept;
[[nodiscard]] Json make_result(const Json& id, Json result);
[[nodiscard]] Json make_error(const Json& id,
                              std::int32_t code,
                              std::string_view message);
[[nodiscard]] Json make_error(const Json& id,
                              std::int32_t code,
                              std::string_view message,
                              Json data);

}  // namespace native_mcp::json_rpc
