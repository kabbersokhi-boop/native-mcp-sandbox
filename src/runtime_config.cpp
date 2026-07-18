#include "native_mcp/runtime_config.hpp"

#include <nlohmann/json.hpp>

#include <cctype>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>

namespace native_mcp {
namespace {

using Json = nlohmann::json;

[[nodiscard]] RuntimeConfigError error(const RuntimeConfigErrorCode code,
                                       std::string message) {
  return RuntimeConfigError{.code = code, .message = std::move(message)};
}

[[nodiscard]] bool valid_process_name(const std::string_view name,
                                      const std::size_t maximum) {
  if (name.empty() || name.size() > maximum) {
    return false;
  }
  for (const char raw : name) {
    const auto value = static_cast<unsigned char>(raw);
    if (!(std::isalnum(value) != 0 || value == '-' || value == '_')) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] std::optional<RuntimeConfigError> parse_roots(
    const Json& roots, RuntimePolicyConfig& config,
    const RuntimeConfigLimits& limits) {
  if (!roots.is_array() || roots.size() > limits.filesystem.max_roots) {
    return error(RuntimeConfigErrorCode::kInvalidConfig,
                 "runtime roots must be an array within the configured limit");
  }
  if (roots.empty()) {
    return std::nullopt;
  }
  const Json legacy{{"version", 1U}, {"roots", roots}};
  const ConfigParseResult parsed = parse_filesystem_policy_config(
      legacy.dump(), limits.filesystem);
  if (!parsed.config.has_value()) {
    return error(RuntimeConfigErrorCode::kInvalidConfig,
                 parsed.error->message);
  }
  config.filesystem = *parsed.config;
  return std::nullopt;
}

[[nodiscard]] std::optional<RuntimeConfigError> parse_processes(
    const Json& processes, RuntimePolicyConfig& config,
    const RuntimeConfigLimits& limits) {
  if (!processes.is_array() ||
      processes.size() > limits.processes.max_processes) {
    return error(RuntimeConfigErrorCode::kInvalidConfig,
                 "runtime processes must be an array within the configured limit");
  }
  std::unordered_set<std::string> names;
  for (const Json& value : processes) {
    if (!value.is_object() || value.size() != 2U || !value.contains("name") ||
        !value.contains("pid") || !value["name"].is_string()) {
      return error(RuntimeConfigErrorCode::kInvalidConfig,
                   "process entries must contain exactly name and pid");
    }
    const std::string name = value["name"].get<std::string>();
    if (!valid_process_name(name, limits.processes.max_name_bytes)) {
      return error(RuntimeConfigErrorCode::kInvalidConfig,
                   "process name contains unsupported characters");
    }
    if (!names.insert(name).second) {
      return error(RuntimeConfigErrorCode::kInvalidConfig,
                   "process names must be unique");
    }

    ProcessTargetConfig target{.name = name, .pid = std::nullopt};
    const Json& pid = value["pid"];
    if (pid.is_string()) {
      if (pid.get_ref<const std::string&>() != "self") {
        return error(RuntimeConfigErrorCode::kInvalidConfig,
                     "process pid strings must be exactly self");
      }
    } else if (pid.is_number_unsigned()) {
      const std::uint64_t raw = pid.get<std::uint64_t>();
      if (raw == 0U || raw > static_cast<std::uint64_t>(
                                 std::numeric_limits<std::int32_t>::max())) {
        return error(RuntimeConfigErrorCode::kInvalidConfig,
                     "process PID is outside the accepted range");
      }
      target.pid = static_cast<std::uint32_t>(raw);
    } else {
      return error(RuntimeConfigErrorCode::kInvalidConfig,
                   "process pid must be an unsigned integer or self");
    }
    config.processes.processes.push_back(std::move(target));
  }
  return std::nullopt;
}

}  // namespace

RuntimeConfigParseResult parse_runtime_policy_config(
    const std::string_view text, RuntimeConfigLimits limits) {
  limits.filesystem.max_config_bytes = limits.max_config_bytes;
  if (text.size() > limits.max_config_bytes) {
    return {.config = std::nullopt,
            .error = error(RuntimeConfigErrorCode::kConfigTooLarge,
                           "runtime policy configuration exceeds the byte limit")};
  }
  Json document = Json::parse(text, nullptr, false);
  if (document.is_discarded() || !document.is_object() ||
      !document.contains("version") ||
      !document["version"].is_number_unsigned()) {
    return {.config = std::nullopt,
            .error = error(RuntimeConfigErrorCode::kInvalidConfig,
                           "runtime policy configuration is not valid JSON schema")};
  }

  const std::uint64_t version = document["version"].get<std::uint64_t>();
  RuntimePolicyConfig config;
  if (version == 1U) {
    if (document.size() != 2U || !document.contains("roots")) {
      return {.config = std::nullopt,
              .error = error(RuntimeConfigErrorCode::kInvalidConfig,
                             "schema version 1 contains only version and roots")};
    }
    const ConfigParseResult parsed =
        parse_filesystem_policy_config(text, limits.filesystem);
    if (!parsed.config.has_value()) {
      return {.config = std::nullopt,
              .error = error(RuntimeConfigErrorCode::kInvalidConfig,
                             parsed.error->message)};
    }
    config.filesystem = *parsed.config;
  } else if (version == 2U) {
    if (document.size() != 3U || !document.contains("roots") ||
        !document.contains("processes")) {
      return {.config = std::nullopt,
              .error = error(RuntimeConfigErrorCode::kInvalidConfig,
                             "schema version 2 requires roots and processes")};
    }
    if (const auto failure =
            parse_roots(document["roots"], config, limits)) {
      return {.config = std::nullopt, .error = failure};
    }
    if (const auto failure =
            parse_processes(document["processes"], config, limits)) {
      return {.config = std::nullopt, .error = failure};
    }
    if (config.filesystem.roots.empty() && config.processes.processes.empty()) {
      return {.config = std::nullopt,
              .error = error(RuntimeConfigErrorCode::kInvalidConfig,
                             "schema version 2 must configure at least one capability")};
    }
  } else {
    return {.config = std::nullopt,
            .error = error(RuntimeConfigErrorCode::kInvalidConfig,
                           "unsupported runtime policy schema version")};
  }

  return {.config = std::move(config), .error = std::nullopt};
}

std::string_view runtime_config_error_name(
    const RuntimeConfigErrorCode code) noexcept {
  switch (code) {
    case RuntimeConfigErrorCode::kConfigTooLarge:
      return "config_too_large";
    case RuntimeConfigErrorCode::kInvalidConfig:
      return "invalid_config";
  }
  return "unknown";
}

}  // namespace native_mcp
