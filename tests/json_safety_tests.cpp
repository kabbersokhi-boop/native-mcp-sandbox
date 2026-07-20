#include "native_mcp/json_safety.hpp"

#include <cstdlib>
#include <iostream>
#include <string>
#include <string_view>

namespace {

using native_mcp::JsonPreflightStatus;
using native_mcp::JsonSafetyLimits;
using native_mcp::preflight_json;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

[[nodiscard]] std::string nested_arrays(const std::size_t depth) {
  return std::string(depth, '[') + "null" + std::string(depth, ']');
}

}  // namespace

int main() {
  expect(preflight_json(R"({"a":[1,true,null,"text"]})") ==
             JsonPreflightStatus::kOk,
         "ordinary JSON must pass preflight");
  expect(preflight_json(R"({"text":"[{not structural}]"})") ==
             JsonPreflightStatus::kOk,
         "brackets inside strings must not affect nesting");
  expect(preflight_json(R"({"a":1,"a":2})") ==
             JsonPreflightStatus::kDuplicateKey,
         "duplicate keys in one object must be rejected");
  expect(preflight_json(R"({"left":{"id":1},"right":{"id":2}})") ==
             JsonPreflightStatus::kOk,
         "equal keys in separate objects must remain valid");
  expect(preflight_json("{broken") == JsonPreflightStatus::kInvalid,
         "invalid syntax must be rejected");

  expect(preflight_json(nested_arrays(64U)) == JsonPreflightStatus::kOk,
         "the documented protocol depth boundary must be accepted");
  expect(preflight_json(nested_arrays(65U)) == JsonPreflightStatus::kTooDeep,
         "JSON beyond the depth boundary must be rejected before DOM parsing");

  constexpr JsonSafetyLimits kThreeTokens{
      .max_nesting_depth = 8U,
      .max_tokens = 3U,
  };
  expect(preflight_json("[1,2]", kThreeTokens) == JsonPreflightStatus::kOk,
         "token limit must include containers and scalar values exactly");
  expect(preflight_json("[1,2,3]", kThreeTokens) ==
             JsonPreflightStatus::kTooManyTokens,
         "token budget exhaustion must stop parsing");

  constexpr JsonSafetyLimits kInvalidLimits{
      .max_nesting_depth = 0U,
      .max_tokens = 1U,
  };
  expect(preflight_json("null", kInvalidLimits) == JsonPreflightStatus::kInvalid,
         "zero limits must fail closed");
  expect(native_mcp::json_preflight_status_name(
             JsonPreflightStatus::kDuplicateKey) == "duplicate_key",
         "preflight statuses must have stable diagnostic names");

  std::cout << "All JSON safety tests passed\n";
  return EXIT_SUCCESS;
}
