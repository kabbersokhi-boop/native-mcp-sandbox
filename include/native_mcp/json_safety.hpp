#pragma once

#include <cstddef>
#include <string_view>

namespace native_mcp {

enum class JsonPreflightStatus {
  kOk,
  kInvalid,
  kTooDeep,
  kTooManyTokens,
  kDuplicateKey,
};

struct JsonSafetyLimits final {
  std::size_t max_nesting_depth = 64U;
  std::size_t max_tokens = 32U * 1024U;
};

[[nodiscard]] JsonPreflightStatus preflight_json(
    std::string_view text, JsonSafetyLimits limits = {}) noexcept;
[[nodiscard]] std::string_view json_preflight_status_name(
    JsonPreflightStatus status) noexcept;

}  // namespace native_mcp
