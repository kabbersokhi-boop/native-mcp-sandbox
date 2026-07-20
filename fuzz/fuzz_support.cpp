#include "fuzz_support.hpp"

#include "native_mcp/elf_analysis.hpp"
#include "native_mcp/file_policy.hpp"
#include "native_mcp/foundation.hpp"
#include "native_mcp/json_safety.hpp"
#include "native_mcp/log_analysis.hpp"
#include "native_mcp/process_parsing.hpp"
#include "native_mcp/runtime_config.hpp"
#include "native_mcp/server.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <unistd.h>
#include <utility>

namespace native_mcp::fuzzing {
namespace {

using Json = nlohmann::json;

[[noreturn]] void invariant_failure(const char* file, const int line) noexcept {
  std::fprintf(stderr, "fuzz invariant failed at %s:%d\n", file, line);
  std::abort();
}

#define NMS_FUZZ_REQUIRE(condition) \
  do { \
    if (!(condition)) { \
      invariant_failure(__FILE__, __LINE__); \
    } \
  } while (false)

[[nodiscard]] std::string bytes_as_string(
    const std::span<const std::uint8_t> input) {
  if (input.empty()) {
    return {};
  }
  return std::string{reinterpret_cast<const char*>(input.data()), input.size()};
}

[[nodiscard]] std::optional<ReadOnlyFile> temporary_file(
    const std::span<const std::uint8_t> input, const std::size_t maximum) {
  if (input.size() > maximum) {
    return std::nullopt;
  }
  char path[] = "/tmp/native-mcp-fuzz-XXXXXX";
  const int descriptor = ::mkstemp(path);
  if (descriptor < 0) {
    return std::nullopt;
  }
  (void)::unlink(path);
  UniqueFd owned{descriptor};
  std::size_t written = 0U;
  while (written < input.size()) {
    const ssize_t count = ::pwrite(
        owned.get(), input.data() + written, input.size() - written,
        static_cast<off_t>(written));
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return std::nullopt;
    }
    if (count == 0) {
      return std::nullopt;
    }
    written += static_cast<std::size_t>(count);
  }
  return ReadOnlyFile{std::move(owned),
                      static_cast<std::uint64_t>(input.size()),
                      static_cast<std::uint64_t>(maximum)};
}

void validate_protocol_result(const ProcessResult& result,
                              const ResourceBudget& budget) {
  if (!result.response.has_value()) {
    return;
  }
  NMS_FUZZ_REQUIRE(result.response->size() <= budget.max_response_bytes);
  NMS_FUZZ_REQUIRE(preflight_json(*result.response) == JsonPreflightStatus::kOk);
  const Json parsed = Json::parse(*result.response, nullptr, false);
  NMS_FUZZ_REQUIRE(!parsed.is_discarded());
  NMS_FUZZ_REQUIRE(parsed.is_object());
  NMS_FUZZ_REQUIRE(parsed.value("jsonrpc", std::string{}) == "2.0");
}

}  // namespace

void exercise_json_and_protocol(const std::span<const std::uint8_t> input) {
  constexpr std::size_t kMaximumInput = 1024U * 1024U;
  if (input.size() > kMaximumInput) {
    return;
  }
  const std::string text = bytes_as_string(input);
  (void)preflight_json(text);

  const ResourceBudget budget = conservative_budget();
  Server server{budget};
  const LineAction action = server.accept_line(text);
  const std::size_t action_count =
      static_cast<std::size_t>(action.immediate.has_value()) +
      static_cast<std::size_t>(action.tool_call.has_value()) +
      static_cast<std::size_t>(action.cancellation.has_value());
  NMS_FUZZ_REQUIRE(action_count <= 1U);
  if (action.immediate.has_value()) {
    validate_protocol_result(*action.immediate, budget);
  }

  Server synchronous{budget};
  validate_protocol_result(synchronous.process_line(text), budget);
}

void exercise_runtime_config(const std::span<const std::uint8_t> input) {
  constexpr std::size_t kMaximumInput = 64U * 1024U;
  if (input.size() > kMaximumInput) {
    return;
  }
  const std::string text = bytes_as_string(input);
  const RuntimeConfigLimits runtime_limits;
  const RuntimeConfigParseResult runtime =
      parse_runtime_policy_config(text, runtime_limits);
  NMS_FUZZ_REQUIRE(runtime.config.has_value() != runtime.error.has_value());
  if (runtime.config.has_value()) {
    NMS_FUZZ_REQUIRE(runtime.config->filesystem.roots.size() <=
            runtime_limits.filesystem.max_roots);
    NMS_FUZZ_REQUIRE(runtime.config->processes.processes.size() <=
            runtime_limits.processes.max_processes);
    NMS_FUZZ_REQUIRE(!runtime.config->filesystem.roots.empty() ||
            !runtime.config->processes.processes.empty());
  }

  const FilesystemPolicyLimits filesystem_limits;
  const ConfigParseResult filesystem =
      parse_filesystem_policy_config(text, filesystem_limits);
  NMS_FUZZ_REQUIRE(filesystem.config.has_value() != filesystem.error.has_value());
  if (filesystem.config.has_value()) {
    NMS_FUZZ_REQUIRE(!filesystem.config->roots.empty());
    NMS_FUZZ_REQUIRE(filesystem.config->roots.size() <= filesystem_limits.max_roots);
  }
}

void exercise_elf(const std::span<const std::uint8_t> input) {
  constexpr std::size_t kMaximumInput = 1024U * 1024U;
  const auto file = temporary_file(input, kMaximumInput);
  if (!file.has_value()) {
    return;
  }
  const ElfInspectionLimits limits;
  const ElfInspectionOutcome outcome = ElfAnalyzer{limits}.inspect(*file);
  NMS_FUZZ_REQUIRE(outcome.result.has_value() != outcome.error.has_value());
  if (!outcome.result.has_value()) {
    return;
  }
  NMS_FUZZ_REQUIRE(outcome.result->metadata_bytes_read <= limits.max_metadata_bytes);
  NMS_FUZZ_REQUIRE(outcome.result->program_header_count <= limits.max_program_headers);
  NMS_FUZZ_REQUIRE(outcome.result->segments.size() <= limits.max_segment_summaries);
  NMS_FUZZ_REQUIRE(outcome.result->needed_libraries.size() <=
          limits.max_needed_libraries);
  if (outcome.result->interpreter.has_value()) {
    NMS_FUZZ_REQUIRE(outcome.result->interpreter->size() <=
            limits.max_interpreter_bytes);
  }
  if (outcome.result->build_id.has_value()) {
    NMS_FUZZ_REQUIRE(outcome.result->build_id->size() <= limits.max_build_id_bytes * 2U);
  }
}

void exercise_log(const std::span<const std::uint8_t> input) {
  constexpr std::size_t kMaximumInput = 256U * 1024U;
  if (input.size() > kMaximumInput) {
    return;
  }
  std::size_t query_size = 0U;
  if (!input.empty()) {
    query_size = 1U + static_cast<std::size_t>(input.front() % 64U);
    query_size = std::min(query_size, input.size());
  }
  const std::span<const std::uint8_t> file_bytes = input.subspan(query_size);
  const auto file = temporary_file(file_bytes, kMaximumInput);
  if (!file.has_value()) {
    return;
  }

  std::string query = input.empty()
                          ? std::string{"x"}
                          : bytes_as_string(input.first(query_size));
  const LogAnalysisLimits limits{
      .max_scan_bytes = kMaximumInput,
      .max_query_bytes = 64U,
      .max_matches = 16U,
      .max_tail_lines = 16U,
      .max_preview_bytes = 128U,
      .read_chunk_bytes = 257U,
  };
  const LogAnalyzer analyzer{limits};
  const LogSearchOutcome searched = analyzer.search(
      *file, LogSearchOptions{.query = std::move(query),
                              .case_sensitive = !input.empty() &&
                                                (input.front() & 1U) != 0U,
                              .max_matches = 16U});
  NMS_FUZZ_REQUIRE(searched.result.has_value() != searched.error.has_value());
  if (searched.result.has_value()) {
    NMS_FUZZ_REQUIRE(searched.result->bytes_scanned <= limits.max_scan_bytes);
    NMS_FUZZ_REQUIRE(searched.result->matches.size() <= limits.max_matches);
    for (const LogMatch& match : searched.result->matches) {
      NMS_FUZZ_REQUIRE(match.preview.size() <= limits.max_preview_bytes * 4U);
    }
  }

  const LogTailOutcome tailed =
      analyzer.tail(*file, LogTailOptions{.max_lines = 16U});
  NMS_FUZZ_REQUIRE(tailed.result.has_value() != tailed.error.has_value());
  if (tailed.result.has_value()) {
    NMS_FUZZ_REQUIRE(tailed.result->bytes_scanned <= limits.max_scan_bytes);
    NMS_FUZZ_REQUIRE(tailed.result->lines.size() <= limits.max_tail_lines);
    for (const LogTailLine& line : tailed.result->lines) {
      NMS_FUZZ_REQUIRE(line.preview.size() <= limits.max_preview_bytes * 4U);
    }
  }
}


void exercise_process(const std::span<const std::uint8_t> input) {
  constexpr std::size_t kMaximumInput = 256U * 1024U;
  if (input.size() > kMaximumInput) {
    return;
  }
  const std::string text = bytes_as_string(input);
  if (const auto identity =
          process_parsing::parse_stat_identity_text(text)) {
    NMS_FUZZ_REQUIRE(identity->name.size() <= input.size());
    NMS_FUZZ_REQUIRE(identity->state.size() == 1U);
  }
  if (const auto status = process_parsing::parse_status_text(text)) {
    NMS_FUZZ_REQUIRE(status->name.size() <= input.size());
    NMS_FUZZ_REQUIRE(status->state.size() <= input.size());
  }
  constexpr std::uint64_t kPageSize = 4096U;
  if (const auto statm =
          process_parsing::parse_statm_text(text, kPageSize)) {
    NMS_FUZZ_REQUIRE(statm->virtual_bytes % kPageSize == 0U);
    NMS_FUZZ_REQUIRE(statm->resident_bytes % kPageSize == 0U);
    NMS_FUZZ_REQUIRE(statm->shared_bytes % kPageSize == 0U);
    NMS_FUZZ_REQUIRE(statm->text_bytes % kPageSize == 0U);
    NMS_FUZZ_REQUIRE(statm->data_and_stack_bytes % kPageSize == 0U);
  }
  (void)process_parsing::parse_smaps_rollup_text(text);
}

}  // namespace native_mcp::fuzzing
