#pragma once

#include "native_mcp/file_policy.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace native_mcp {

enum class LogAnalysisErrorCode {
  kInvalidArguments,
  kInputTooLarge,
  kReadFailed,
};

struct LogAnalysisError final {
  LogAnalysisErrorCode code;
  std::string message;
};

struct LogAnalysisLimits final {
  std::uint64_t max_scan_bytes = 16ULL * 1024ULL * 1024ULL;
  std::size_t max_query_bytes = 256U;
  std::size_t max_matches = 50U;
  std::size_t max_tail_lines = 50U;
  std::size_t max_preview_bytes = 512U;
  std::size_t read_chunk_bytes = 8U * 1024U;
};

struct LogSearchOptions final {
  std::string query;
  bool case_sensitive = true;
  std::size_t max_matches = 20U;
};

struct LogMatch final {
  std::uint64_t line_number;
  std::uint64_t byte_offset;
  std::string preview;
  bool preview_truncated_start;
  bool preview_truncated_end;
};

struct LogSearchResult final {
  std::uint64_t bytes_scanned = 0U;
  std::uint64_t lines_scanned = 0U;
  bool match_limit_reached = false;
  bool file_changed_during_read = false;
  std::vector<LogMatch> matches;
};

struct LogSearchOutcome final {
  std::optional<LogSearchResult> result;
  std::optional<LogAnalysisError> error;
};

struct LogTailOptions final {
  std::size_t max_lines = 20U;
};

struct LogTailLine final {
  std::uint64_t line_number;
  std::uint64_t byte_offset;
  std::string preview;
  bool preview_truncated_start;
};

struct LogTailResult final {
  std::uint64_t bytes_scanned = 0U;
  std::uint64_t lines_scanned = 0U;
  bool file_changed_during_read = false;
  std::vector<LogTailLine> lines;
};

struct LogTailOutcome final {
  std::optional<LogTailResult> result;
  std::optional<LogAnalysisError> error;
};

class LogAnalyzer final {
 public:
  explicit LogAnalyzer(LogAnalysisLimits limits = {});

  [[nodiscard]] LogSearchOutcome search(const ReadOnlyFile& file,
                                        const LogSearchOptions& options) const;
  [[nodiscard]] LogTailOutcome tail(const ReadOnlyFile& file,
                                    const LogTailOptions& options) const;
  [[nodiscard]] const LogAnalysisLimits& limits() const noexcept;

 private:
  LogAnalysisLimits limits_;
};

[[nodiscard]] std::string_view log_analysis_error_name(
    LogAnalysisErrorCode code) noexcept;

}  // namespace native_mcp
