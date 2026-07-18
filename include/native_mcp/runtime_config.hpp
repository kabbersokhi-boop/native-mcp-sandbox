#pragma once

#include "native_mcp/file_policy.hpp"
#include "native_mcp/process_memory.hpp"

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>

namespace native_mcp {

enum class RuntimeConfigErrorCode {
  kConfigTooLarge,
  kInvalidConfig,
};

struct RuntimeConfigError final {
  RuntimeConfigErrorCode code;
  std::string message;
};

struct RuntimePolicyConfig final {
  FilesystemPolicyConfig filesystem;
  ProcessPolicyConfig processes;
};

struct RuntimeConfigLimits final {
  std::size_t max_config_bytes = 64U * 1024U;
  FilesystemPolicyLimits filesystem{};
  ProcessPolicyLimits processes{};
};

struct RuntimeConfigParseResult final {
  std::optional<RuntimePolicyConfig> config;
  std::optional<RuntimeConfigError> error;
};

[[nodiscard]] RuntimeConfigParseResult parse_runtime_policy_config(
    std::string_view text, RuntimeConfigLimits limits = {});
[[nodiscard]] std::string_view runtime_config_error_name(
    RuntimeConfigErrorCode code) noexcept;

}  // namespace native_mcp
