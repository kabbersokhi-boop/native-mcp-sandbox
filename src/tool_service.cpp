#include "native_mcp/tool_service.hpp"

#include <cstddef>
#include <chrono>
#include <cstdint>
#include <initializer_list>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

namespace native_mcp {
namespace {

using Json = nlohmann::json;

constexpr std::string_view kSearchTool = "logs.search";
constexpr std::string_view kTailTool = "logs.tail";
constexpr std::string_view kElfInspectTool = "elf.inspect";

[[nodiscard]] bool has_only_fields(
    const Json& object, const std::initializer_list<std::string_view> allowed) {
  for (auto iterator = object.begin(); iterator != object.end(); ++iterator) {
    bool accepted = false;
    for (const std::string_view field : allowed) {
      if (iterator.key() == field) {
        accepted = true;
        break;
      }
    }
    if (!accepted) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] ToolExecutionResult tool_error(const std::string_view code,
                                              const std::string_view message) {
  return ToolExecutionResult{
      .is_error = true,
      .structured_content =
          Json{{"error", Json{{"code", code}, {"message", message}}}},
  };
}

[[nodiscard]] ToolExecutionResult policy_error_result(const PolicyError& failure) {
  return tool_error(policy_error_name(failure.code), failure.message);
}

[[nodiscard]] ToolExecutionResult analysis_error_result(
    const LogAnalysisError& failure) {
  return tool_error(log_analysis_error_name(failure.code), failure.message);
}

[[nodiscard]] ToolExecutionResult elf_error_result(
    const ElfAnalysisError& failure) {
  return tool_error(elf_analysis_error_name(failure.code), failure.message);
}

[[nodiscard]] Json common_annotations() {
  return Json{{"readOnlyHint", true},
              {"destructiveHint", false},
              {"openWorldHint", false}};
}

[[nodiscard]] Json search_definition(const LogAnalysisLimits& limits) {
  return Json{
      {"name", kSearchTool},
      {"title", "Search approved logs"},
      {"description",
       "Search matching lines in one approved regular log file for a bounded literal "
       "byte sequence. At most one result is returned per line, using the first "
       "occurrence. Paths are resolved only through an operator-configured root. "
       "The scan is "
       "streaming, synchronous, read-only, and limited to 16 MiB."},
      {"inputSchema",
       Json{{"type", "object"},
            {"additionalProperties", false},
            {"properties",
             Json{{"root",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", 64},
                        {"description", "Operator-configured symbolic root name"}}},
                  {"path",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", 4096},
                        {"description", "Relative path beneath the selected root"}}},
                  {"query",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", limits.max_query_bytes},
                        {"description", "Literal text or UTF-8 byte sequence to find"}}},
                  {"caseSensitive",
                   Json{{"type", "boolean"},
                        {"default", true},
                        {"description", "Use exact byte case; false folds ASCII letters only"}}},
                  {"maxMatches",
                   Json{{"type", "integer"},
                        {"minimum", 1},
                        {"maximum", limits.max_matches},
                        {"default", 20},
                        {"description", "Maximum matching lines to return"}}}}},
            {"required", Json::array({"root", "path", "query"})}}},
      {"outputSchema",
       Json{{"type", "object"},
            {"properties",
             Json{{"root", Json{{"type", "string"}}},
                  {"path", Json{{"type", "string"}}},
                  {"caseSensitive", Json{{"type", "boolean"}}},
                  {"bytesScanned", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"linesScanned", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"matchLimitReached", Json{{"type", "boolean"}}},
                  {"fileChangedDuringRead", Json{{"type", "boolean"}}},
                  {"matches",
                   Json{{"type", "array"},
                        {"items",
                         Json{{"type", "object"},
                              {"properties",
                               Json{{"line", Json{{"type", "integer"}, {"minimum", 1}}},
                                    {"byteOffset",
                                     Json{{"type", "integer"}, {"minimum", 0}}},
                                    {"preview", Json{{"type", "string"}}},
                                    {"previewTruncatedStart", Json{{"type", "boolean"}}},
                                    {"previewTruncatedEnd", Json{{"type", "boolean"}}}}},
                              {"required",
                               Json::array({"line", "byteOffset", "preview",
                                            "previewTruncatedStart",
                                            "previewTruncatedEnd"})}}}}}}},
            {"required",
             Json::array({"root", "path", "caseSensitive", "bytesScanned",
                          "linesScanned", "matchLimitReached",
                          "fileChangedDuringRead", "matches"})}}},
      {"annotations", common_annotations()},
      {"execution", Json{{"taskSupport", "forbidden"}}},
  };
}

[[nodiscard]] Json tail_definition(const LogAnalysisLimits& limits) {
  return Json{
      {"name", kTailTool},
      {"title", "Read the end of an approved log"},
      {"description",
       "Return a bounded preview of the final logical lines from one approved regular "
       "log file. The file is streamed from a pinned read-only descriptor; long lines "
       "retain only their final preview bytes."},
      {"inputSchema",
       Json{{"type", "object"},
            {"additionalProperties", false},
            {"properties",
             Json{{"root",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", 64},
                        {"description", "Operator-configured symbolic root name"}}},
                  {"path",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", 4096},
                        {"description", "Relative path beneath the selected root"}}},
                  {"maxLines",
                   Json{{"type", "integer"},
                        {"minimum", 1},
                        {"maximum", limits.max_tail_lines},
                        {"default", 20}}}}},
            {"required", Json::array({"root", "path"})}}},
      {"outputSchema",
       Json{{"type", "object"},
            {"properties",
             Json{{"root", Json{{"type", "string"}}},
                  {"path", Json{{"type", "string"}}},
                  {"bytesScanned", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"linesScanned", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"fileChangedDuringRead", Json{{"type", "boolean"}}},
                  {"lines",
                   Json{{"type", "array"},
                        {"items",
                         Json{{"type", "object"},
                              {"properties",
                               Json{{"line", Json{{"type", "integer"}, {"minimum", 1}}},
                                    {"byteOffset",
                                     Json{{"type", "integer"}, {"minimum", 0}}},
                                    {"preview", Json{{"type", "string"}}},
                                    {"previewTruncatedStart", Json{{"type", "boolean"}}}}},
                              {"required",
                               Json::array({"line", "byteOffset", "preview",
                                            "previewTruncatedStart"})}}}}}}},
            {"required",
             Json::array({"root", "path", "bytesScanned", "linesScanned",
                          "fileChangedDuringRead", "lines"})}}},
      {"annotations", common_annotations()},
      {"execution", Json{{"taskSupport", "forbidden"}}},
  };
}

[[nodiscard]] Json elf_definition(const ElfInspectionLimits& limits) {
  return Json{
      {"name", kElfInspectTool},
      {"title", "Inspect an approved Linux ELF file"},
      {"description",
       "Inspect bounded ELF metadata from one approved regular file without executing "
       "or memory-mapping it. Reports identity, interpreter, dependencies, build ID, "
       "segment summaries, and common hardening signals."},
      {"inputSchema",
       Json{{"type", "object"},
            {"additionalProperties", false},
            {"properties",
             Json{{"root",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", 64},
                        {"description", "Operator-configured symbolic root name"}}},
                  {"path",
                   Json{{"type", "string"},
                        {"minLength", 1},
                        {"maxLength", 4096},
                        {"description", "Relative path beneath the selected root"}}}}},
            {"required", Json::array({"root", "path"})}}},
      {"outputSchema",
       Json{{"type", "object"},
            {"properties",
             Json{{"root", Json{{"type", "string"}}},
                  {"path", Json{{"type", "string"}}},
                  {"class", Json{{"type", "string"}}},
                  {"endianness", Json{{"type", "string"}}},
                  {"fileType", Json{{"type", "string"}}},
                  {"fileTypeNumber", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"machine", Json{{"type", "string"}}},
                  {"machineNumber", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"osAbi", Json{{"type", "string"}}},
                  {"osAbiNumber", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"entryPoint", Json{{"type", "string"}}},
                  {"programHeaderCount", Json{{"type", "integer"}, {"minimum", 0},
                                               {"maximum", limits.max_program_headers}}},
                  {"interpreter", Json{{"type", {"string", "null"}}}},
                  {"neededLibraries", Json{{"type", "array"},
                                            {"items", Json{{"type", "string"}}}}},
                  {"neededLibrariesTruncated", Json{{"type", "boolean"}}},
                  {"buildId", Json{{"type", {"string", "null"}}}},
                  {"stackPolicy", Json{{"type", "string"}}},
                  {"relro", Json{{"type", "string"}}},
                  {"positionIndependent", Json{{"type", "boolean"}}},
                  {"pieExecutable", Json{{"type", "boolean"}}},
                  {"writableExecutableLoadSegment", Json{{"type", "boolean"}}},
                  {"fileChangedDuringRead", Json{{"type", "boolean"}}},
                  {"metadataBytesRead", Json{{"type", "integer"}, {"minimum", 0}}},
                  {"segments",
                   Json{{"type", "array"},
                        {"items",
                         Json{{"type", "object"},
                              {"properties",
                               Json{{"type", Json{{"type", "string"}}},
                                    {"flags", Json{{"type", "string"}}},
                                    {"fileOffset", Json{{"type", "integer"}, {"minimum", 0}}},
                                    {"fileSize", Json{{"type", "integer"}, {"minimum", 0}}},
                                    {"memorySize", Json{{"type", "integer"}, {"minimum", 0}}},
                                    {"virtualAddress", Json{{"type", "string"}}}}},
                              {"required", Json::array({"type", "flags", "fileOffset",
                                                        "fileSize", "memorySize",
                                                        "virtualAddress"})}}}}},
                  {"segmentSummariesTruncated", Json{{"type", "boolean"}}}}},
            {"required",
             Json::array({"root", "path", "class", "endianness", "fileType",
                          "fileTypeNumber", "machine", "machineNumber", "osAbi",
                          "osAbiNumber", "entryPoint", "programHeaderCount",
                          "interpreter", "neededLibraries", "neededLibrariesTruncated",
                          "buildId", "stackPolicy", "relro", "positionIndependent",
                          "pieExecutable", "writableExecutableLoadSegment",
                          "fileChangedDuringRead", "metadataBytesRead", "segments",
                          "segmentSummariesTruncated"})}}},
      {"annotations", common_annotations()},
      {"execution", Json{{"taskSupport", "forbidden"}}},
  };
}

[[nodiscard]] std::optional<std::string> required_string(
    const Json& arguments, const char* name) {
  const auto value = arguments.find(name);
  if (value == arguments.end() || !value->is_string() ||
      value->get_ref<const std::string&>().empty()) {
    return std::nullopt;
  }
  return value->get<std::string>();
}

[[nodiscard]] std::optional<std::size_t> optional_bounded_size(
    const Json& arguments, const char* name, const std::size_t fallback,
    const std::size_t maximum) {
  const auto value = arguments.find(name);
  if (value == arguments.end()) {
    return fallback;
  }
  if (!value->is_number_unsigned()) {
    return std::nullopt;
  }
  const std::uint64_t raw = value->get<std::uint64_t>();
  if (raw == 0U || raw > maximum) {
    return std::nullopt;
  }
  return static_cast<std::size_t>(raw);
}

[[nodiscard]] ToolExecutionResult execute_search(
    const FilesystemPolicy& policy, const LogAnalyzer& analyzer,
    const Json& arguments) {
  if (!arguments.is_object() ||
      !has_only_fields(arguments,
                       {"root", "path", "query", "caseSensitive",
                        "maxMatches"})) {
    return tool_error("invalid_arguments",
                      "logs.search arguments must match the closed schema");
  }
  const auto root = required_string(arguments, "root");
  const auto path = required_string(arguments, "path");
  const auto query = required_string(arguments, "query");
  if (!root.has_value() || !path.has_value() || !query.has_value()) {
    return tool_error("invalid_arguments",
                      "root, path, and query must be nonempty strings");
  }

  bool case_sensitive = true;
  const auto case_value = arguments.find("caseSensitive");
  if (case_value != arguments.end()) {
    if (!case_value->is_boolean()) {
      return tool_error("invalid_arguments",
                        "caseSensitive must be a boolean");
    }
    case_sensitive = case_value->get<bool>();
  }
  const auto max_matches = optional_bounded_size(
      arguments, "maxMatches", 20U, analyzer.limits().max_matches);
  if (!max_matches.has_value()) {
    return tool_error("invalid_arguments",
                      "maxMatches must be a positive bounded integer");
  }

  auto opened = policy.open_regular_file(*root, *path);
  if (!opened.file.has_value()) {
    return policy_error_result(*opened.error);
  }
  LogSearchOutcome searched = analyzer.search(
      *opened.file,
      LogSearchOptions{.query = *query,
                       .case_sensitive = case_sensitive,
                       .max_matches = *max_matches});
  if (!searched.result.has_value()) {
    return analysis_error_result(*searched.error);
  }

  Json matches = Json::array();
  for (const LogMatch& match : searched.result->matches) {
    matches.push_back(Json{{"line", match.line_number},
                           {"byteOffset", match.byte_offset},
                           {"preview", match.preview},
                           {"previewTruncatedStart",
                            match.preview_truncated_start},
                           {"previewTruncatedEnd",
                            match.preview_truncated_end}});
  }
  return ToolExecutionResult{
      .is_error = false,
      .structured_content =
          Json{{"root", *root},
               {"path", *path},
               {"caseSensitive", case_sensitive},
               {"bytesScanned", searched.result->bytes_scanned},
               {"linesScanned", searched.result->lines_scanned},
               {"matchLimitReached",
                searched.result->match_limit_reached},
               {"fileChangedDuringRead",
                searched.result->file_changed_during_read},
               {"matches", std::move(matches)}},
  };
}

[[nodiscard]] ToolExecutionResult execute_tail(
    const FilesystemPolicy& policy, const LogAnalyzer& analyzer,
    const Json& arguments) {
  if (!arguments.is_object() ||
      !has_only_fields(arguments, {"root", "path", "maxLines"})) {
    return tool_error("invalid_arguments",
                      "logs.tail arguments must match the closed schema");
  }
  const auto root = required_string(arguments, "root");
  const auto path = required_string(arguments, "path");
  if (!root.has_value() || !path.has_value()) {
    return tool_error("invalid_arguments",
                      "root and path must be nonempty strings");
  }
  const auto max_lines = optional_bounded_size(
      arguments, "maxLines", 20U, analyzer.limits().max_tail_lines);
  if (!max_lines.has_value()) {
    return tool_error("invalid_arguments",
                      "maxLines must be a positive bounded integer");
  }

  auto opened = policy.open_regular_file(*root, *path);
  if (!opened.file.has_value()) {
    return policy_error_result(*opened.error);
  }
  LogTailOutcome tailed =
      analyzer.tail(*opened.file, LogTailOptions{.max_lines = *max_lines});
  if (!tailed.result.has_value()) {
    return analysis_error_result(*tailed.error);
  }

  Json lines = Json::array();
  for (const LogTailLine& line : tailed.result->lines) {
    lines.push_back(Json{{"line", line.line_number},
                         {"byteOffset", line.byte_offset},
                         {"preview", line.preview},
                         {"previewTruncatedStart",
                          line.preview_truncated_start}});
  }
  return ToolExecutionResult{
      .is_error = false,
      .structured_content =
          Json{{"root", *root},
               {"path", *path},
               {"bytesScanned", tailed.result->bytes_scanned},
               {"linesScanned", tailed.result->lines_scanned},
               {"fileChangedDuringRead",
                tailed.result->file_changed_during_read},
               {"lines", std::move(lines)}},
  };
}


[[nodiscard]] ToolExecutionResult execute_elf(
    const FilesystemPolicy& policy, const ElfAnalyzer& analyzer,
    const Json& arguments) {
  if (!arguments.is_object() || !has_only_fields(arguments, {"root", "path"})) {
    return tool_error("invalid_arguments",
                      "elf.inspect arguments must match the closed schema");
  }
  const auto root = required_string(arguments, "root");
  const auto path = required_string(arguments, "path");
  if (!root.has_value() || !path.has_value()) {
    return tool_error("invalid_arguments",
                      "root and path must be nonempty strings");
  }
  auto opened = policy.open_regular_file(*root, *path);
  if (!opened.file.has_value()) {
    return policy_error_result(*opened.error);
  }
  ElfInspectionOutcome inspected = analyzer.inspect(*opened.file);
  if (!inspected.result.has_value()) {
    return elf_error_result(*inspected.error);
  }

  Json segments = Json::array();
  for (const ElfSegmentSummary& segment : inspected.result->segments) {
    segments.push_back(Json{{"type", segment.type},
                            {"flags", segment.flags},
                            {"fileOffset", segment.file_offset},
                            {"fileSize", segment.file_size},
                            {"memorySize", segment.memory_size},
                            {"virtualAddress", segment.virtual_address}});
  }
  Json interpreter = inspected.result->interpreter.has_value()
                         ? Json(*inspected.result->interpreter)
                         : Json(nullptr);
  Json build_id = inspected.result->build_id.has_value()
                      ? Json(*inspected.result->build_id)
                      : Json(nullptr);
  return ToolExecutionResult{
      .is_error = false,
      .structured_content =
          Json{{"root", *root},
               {"path", *path},
               {"class", inspected.result->elf_class},
               {"endianness", inspected.result->endianness},
               {"fileType", inspected.result->file_type},
               {"fileTypeNumber", inspected.result->file_type_number},
               {"machine", inspected.result->machine},
               {"machineNumber", inspected.result->machine_number},
               {"osAbi", inspected.result->os_abi},
               {"osAbiNumber", inspected.result->os_abi_number},
               {"entryPoint", inspected.result->entry_point},
               {"programHeaderCount", inspected.result->program_header_count},
               {"interpreter", std::move(interpreter)},
               {"neededLibraries", inspected.result->needed_libraries},
               {"neededLibrariesTruncated",
                inspected.result->needed_libraries_truncated},
               {"buildId", std::move(build_id)},
               {"stackPolicy", inspected.result->stack_policy},
               {"relro", inspected.result->relro},
               {"positionIndependent", inspected.result->position_independent},
               {"pieExecutable", inspected.result->pie_executable},
               {"writableExecutableLoadSegment",
                inspected.result->writable_executable_load_segment},
               {"fileChangedDuringRead",
                inspected.result->file_changed_during_read},
               {"metadataBytesRead", inspected.result->metadata_bytes_read},
               {"segments", std::move(segments)},
               {"segmentSummariesTruncated",
                inspected.result->segment_summaries_truncated}},
  };
}

}  // namespace

ToolService::ToolService(FilesystemPolicy policy,
                         const LogAnalysisLimits log_limits,
                         const ElfInspectionLimits elf_limits)
    : policy_(std::move(policy)),
      log_analyzer_(log_limits),
      elf_analyzer_(elf_limits) {}

Json ToolService::tool_definitions() const {
  return Json::array(
      {search_definition(log_analyzer_.limits()),
       tail_definition(log_analyzer_.limits()),
       elf_definition(elf_analyzer_.limits())});
}

bool ToolService::knows_tool(const std::string_view name) const noexcept {
  return name == kSearchTool || name == kTailTool || name == kElfInspectTool;
}

bool ToolService::acquire_rate_limit_slot() {
  constexpr std::size_t kMaxCallsPerWindow = 16U;
  constexpr auto kWindow = std::chrono::seconds{1};
  const auto now = std::chrono::steady_clock::now();
  while (!recent_calls_.empty() && now - recent_calls_.front() >= kWindow) {
    recent_calls_.pop_front();
  }
  if (recent_calls_.size() >= kMaxCallsPerWindow) {
    return false;
  }
  recent_calls_.push_back(now);
  return true;
}

ToolExecutionResult ToolService::execute(
    const std::string_view name, const Json& arguments) {
  if (!acquire_rate_limit_slot()) {
    return tool_error("rate_limited",
                      "too many tool calls; retry after a short pause");
  }
  if (name == kSearchTool) {
    return execute_search(policy_, log_analyzer_, arguments);
  }
  if (name == kTailTool) {
    return execute_tail(policy_, log_analyzer_, arguments);
  }
  if (name == kElfInspectTool) {
    return execute_elf(policy_, elf_analyzer_, arguments);
  }
  return tool_error("unknown_tool", "requested tool is not available");
}

}  // namespace native_mcp
