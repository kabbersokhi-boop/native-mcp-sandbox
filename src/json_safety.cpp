#include "native_mcp/json_safety.hpp"

#include <nlohmann/json.hpp>

#include <cstddef>
#include <string>
#include <set>
#include <utility>
#include <vector>

namespace native_mcp {
namespace {

using Json = nlohmann::json;

class SafetySax final : public nlohmann::json_sax<Json> {
 public:
  explicit SafetySax(const JsonSafetyLimits limits) : limits_(limits) {}

  bool null() override { return scalar(); }
  bool boolean(const bool) override { return scalar(); }
  bool number_integer(const number_integer_t) override { return scalar(); }
  bool number_unsigned(const number_unsigned_t) override { return scalar(); }
  bool number_float(const number_float_t, const string_t&) override {
    return scalar();
  }
  bool string(string_t&) override { return scalar(); }
  bool binary(binary_t&) override { return scalar(); }

  bool start_object(const std::size_t) override {
    if (!begin_container()) {
      return false;
    }
    object_keys_.emplace_back();
    return true;
  }

  bool key(string_t& value) override {
    if (!count_token()) {
      return false;
    }
    if (object_keys_.empty()) {
      status_ = JsonPreflightStatus::kInvalid;
      return false;
    }
    if (!object_keys_.back().insert(value).second) {
      status_ = JsonPreflightStatus::kDuplicateKey;
      return false;
    }
    return true;
  }

  bool end_object() override {
    if (object_keys_.empty() || depth_ == 0U) {
      status_ = JsonPreflightStatus::kInvalid;
      return false;
    }
    object_keys_.pop_back();
    --depth_;
    return true;
  }

  bool start_array(const std::size_t) override { return begin_container(); }

  bool end_array() override {
    if (depth_ == 0U) {
      status_ = JsonPreflightStatus::kInvalid;
      return false;
    }
    --depth_;
    return true;
  }

  bool parse_error(const std::size_t, const std::string&,
                   const nlohmann::detail::exception&) override {
    if (status_ == JsonPreflightStatus::kOk) {
      status_ = JsonPreflightStatus::kInvalid;
    }
    return false;
  }

  [[nodiscard]] JsonPreflightStatus status() const noexcept { return status_; }

 private:
  [[nodiscard]] bool count_token() {
    if (token_count_ >= limits_.max_tokens) {
      status_ = JsonPreflightStatus::kTooManyTokens;
      return false;
    }
    ++token_count_;
    return true;
  }

  [[nodiscard]] bool scalar() { return count_token(); }

  [[nodiscard]] bool begin_container() {
    if (!count_token()) {
      return false;
    }
    if (depth_ >= limits_.max_nesting_depth) {
      status_ = JsonPreflightStatus::kTooDeep;
      return false;
    }
    ++depth_;
    return true;
  }

  JsonSafetyLimits limits_;
  JsonPreflightStatus status_ = JsonPreflightStatus::kOk;
  std::size_t depth_ = 0U;
  std::size_t token_count_ = 0U;
  std::vector<std::set<std::string>> object_keys_;
};

}  // namespace

JsonPreflightStatus preflight_json(const std::string_view text,
                                   const JsonSafetyLimits limits) noexcept {
  if (limits.max_nesting_depth == 0U || limits.max_tokens == 0U) {
    return JsonPreflightStatus::kInvalid;
  }

  try {
    SafetySax sax{limits};
    const bool parsed = Json::sax_parse(text.begin(), text.end(), &sax,
                                        Json::input_format_t::json, true, false);
    if (!parsed) {
      return sax.status() == JsonPreflightStatus::kOk
                 ? JsonPreflightStatus::kInvalid
                 : sax.status();
    }
    return sax.status();
  } catch (...) {
    return JsonPreflightStatus::kInvalid;
  }
}

std::string_view json_preflight_status_name(
    const JsonPreflightStatus status) noexcept {
  switch (status) {
    case JsonPreflightStatus::kOk:
      return "ok";
    case JsonPreflightStatus::kInvalid:
      return "invalid";
    case JsonPreflightStatus::kTooDeep:
      return "too_deep";
    case JsonPreflightStatus::kTooManyTokens:
      return "too_many_tokens";
    case JsonPreflightStatus::kDuplicateKey:
      return "duplicate_key";
  }
  return "unknown";
}

}  // namespace native_mcp
