#include "native_mcp/log_analysis.hpp"

#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <iterator>
#include <limits>
#include <string>
#include <utility>
#include <vector>

namespace native_mcp {
namespace {

[[nodiscard]] LogAnalysisError error(const LogAnalysisErrorCode code,
                                     std::string message) {
  return LogAnalysisError{.code = code, .message = std::move(message)};
}

[[nodiscard]] std::optional<LogAnalysisError> operation_error(
    const OperationContext& context) {
  switch (context.stop_reason()) {
    case OperationStopReason::kCancelled:
      return error(LogAnalysisErrorCode::kCancelled,
                   "log analysis was cancelled");
    case OperationStopReason::kDeadlineExceeded:
      return error(LogAnalysisErrorCode::kDeadlineExceeded,
                   "log analysis exceeded its deadline");
    case OperationStopReason::kNone:
      return std::nullopt;
  }
  return std::nullopt;
}

[[nodiscard]] unsigned char fold_ascii(const unsigned char value) noexcept {
  if (value >= static_cast<unsigned char>('A') &&
      value <= static_cast<unsigned char>('Z')) {
    return static_cast<unsigned char>(value +
                                      (static_cast<unsigned char>('a') -
                                       static_cast<unsigned char>('A')));
  }
  return value;
}

[[nodiscard]] unsigned char comparable(const unsigned char value,
                                       const bool case_sensitive) noexcept {
  return case_sensitive ? value : fold_ascii(value);
}

[[nodiscard]] std::string escape_preview(
    const std::deque<unsigned char>& bytes) {
  static constexpr std::array<char, 16> kHex{
      '0', '1', '2', '3', '4', '5', '6', '7',
      '8', '9', 'A', 'B', 'C', 'D', 'E', 'F'};
  std::string output;
  output.reserve(bytes.size());
  for (const unsigned char value : bytes) {
    if (value == static_cast<unsigned char>('\t')) {
      output += "\\t";
    } else if (value >= 0x20U && value <= 0x7EU) {
      output.push_back(static_cast<char>(value));
    } else {
      output += "\\x";
      output.push_back(kHex[(value >> 4U) & 0x0FU]);
      output.push_back(kHex[value & 0x0FU]);
    }
  }
  return output;
}

[[nodiscard]] std::vector<std::size_t> build_failure_table(
    const std::vector<unsigned char>& pattern) {
  std::vector<std::size_t> failure(pattern.size(), 0U);
  std::size_t matched = 0U;
  for (std::size_t index = 1U; index < pattern.size(); ++index) {
    while (matched > 0U && pattern[index] != pattern[matched]) {
      matched = failure[matched - 1U];
    }
    if (pattern[index] == pattern[matched]) {
      ++matched;
    }
    failure[index] = matched;
  }
  return failure;
}

[[nodiscard]] bool query_is_valid(const std::string& query,
                                  const LogAnalysisLimits& limits) {
  if (query.empty() || query.size() > limits.max_query_bytes) {
    return false;
  }
  return query.find('\0') == std::string::npos &&
         query.find('\n') == std::string::npos &&
         query.find('\r') == std::string::npos;
}

[[nodiscard]] bool file_size_changed(const ReadOnlyFile& file) noexcept {
  struct stat metadata {};
  if (::fstat(file.fd(), &metadata) != 0 || metadata.st_size < 0) {
    return true;
  }
  return static_cast<std::uint64_t>(metadata.st_size) != file.observed_size();
}

}  // namespace

LogAnalyzer::LogAnalyzer(const LogAnalysisLimits limits) : limits_(limits) {}

LogSearchOutcome LogAnalyzer::search(const ReadOnlyFile& file,
                                     const LogSearchOptions& options,
                                     const OperationContext context) const {
  if (const auto stopped = operation_error(context)) {
    return {.result = std::nullopt, .error = stopped};
  }
  if (!query_is_valid(options.query, limits_) || options.max_matches == 0U ||
      options.max_matches > limits_.max_matches ||
      limits_.max_preview_bytes == 0U || limits_.read_chunk_bytes == 0U) {
    return {.result = std::nullopt,
            .error = error(LogAnalysisErrorCode::kInvalidArguments,
                           "search arguments are outside the accepted limits")};
  }
  if (file.observed_size() > limits_.max_scan_bytes) {
    return {.result = std::nullopt,
            .error = error(LogAnalysisErrorCode::kInputTooLarge,
                           "log file exceeds the synchronous scan limit")};
  }

  std::vector<unsigned char> pattern;
  pattern.reserve(options.query.size());
  for (const char raw_value : options.query) {
    const auto value = static_cast<unsigned char>(raw_value);
    pattern.push_back(comparable(value, options.case_sensitive));
  }
  const std::vector<std::size_t> failure = build_failure_table(pattern);

  LogSearchResult result;
  result.matches.reserve(options.max_matches);
  const std::uint64_t read_limit =
      std::min(file.observed_size(), file.max_read_bytes());
  std::vector<unsigned char> buffer(limits_.read_chunk_bytes);

  std::uint64_t absolute_offset = 0U;
  std::uint64_t line_number = 1U;
  std::uint64_t line_start_offset = 0U;
  std::uint64_t line_bytes = 0U;
  std::size_t matched = 0U;
  const std::size_t before_budget = limits_.max_preview_bytes / 2U;
  const std::size_t recent_capacity =
      std::min(limits_.max_preview_bytes, before_budget + pattern.size());
  std::deque<unsigned char> recent;
  std::deque<unsigned char> preview;
  bool found = false;
  bool preview_truncated_start = false;
  bool preview_truncated_end = false;
  std::uint64_t match_offset = 0U;
  std::size_t capture_remaining = 0U;
  bool have_unterminated_line = false;
  bool stop = false;

  const auto reset_line = [&]() {
    line_bytes = 0U;
    matched = 0U;
    recent.clear();
    preview.clear();
    found = false;
    preview_truncated_start = false;
    preview_truncated_end = false;
    match_offset = 0U;
    capture_remaining = 0U;
    have_unterminated_line = false;
  };

  const auto finish_line = [&]() {
    ++result.lines_scanned;
    if (found) {
      if (!preview.empty() &&
          preview.back() == static_cast<unsigned char>('\r')) {
        preview.pop_back();
      }
      result.matches.push_back(LogMatch{
          .line_number = line_number,
          .byte_offset = match_offset,
          .preview = escape_preview(preview),
          .preview_truncated_start = preview_truncated_start,
          .preview_truncated_end = preview_truncated_end,
      });
      if (result.matches.size() >= options.max_matches) {
        result.match_limit_reached = true;
        stop = true;
      }
    }
    ++line_number;
    line_start_offset = absolute_offset + 1U;
    reset_line();
  };

  while (absolute_offset < read_limit && !stop) {
    if (const auto stopped = operation_error(context)) {
      return {.result = std::nullopt, .error = stopped};
    }
    const std::uint64_t remaining = read_limit - absolute_offset;
    const std::size_t requested = static_cast<std::size_t>(
        std::min<std::uint64_t>(remaining, buffer.size()));
    const ssize_t count = ::pread(file.fd(), buffer.data(), requested,
                                  static_cast<off_t>(absolute_offset));
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return {.result = std::nullopt,
              .error = error(LogAnalysisErrorCode::kReadFailed,
                             "failed while reading the approved log file")};
    }
    if (count == 0) {
      result.file_changed_during_read = absolute_offset < read_limit;
      break;
    }

    const auto available = static_cast<std::size_t>(count);
    for (std::size_t index = 0U; index < available && !stop; ++index) {
      const unsigned char value = buffer[index];
      if (value == static_cast<unsigned char>('\n')) {
        finish_line();
        ++absolute_offset;
        continue;
      }

      have_unterminated_line = true;
      ++line_bytes;
      if (found) {
        if (capture_remaining > 0U) {
          preview.push_back(value);
          --capture_remaining;
        } else {
          preview_truncated_end = true;
        }
      } else {
        recent.push_back(value);
        if (recent.size() > recent_capacity) {
          recent.pop_front();
        }

        const unsigned char current = comparable(value, options.case_sensitive);
        while (matched > 0U && current != pattern[matched]) {
          matched = failure[matched - 1U];
        }
        if (current == pattern[matched]) {
          ++matched;
        }
        if (matched == pattern.size()) {
          found = true;
          match_offset = absolute_offset + 1U -
                         static_cast<std::uint64_t>(pattern.size());
          preview = recent;
          preview_truncated_start = line_bytes > preview.size();
          capture_remaining = limits_.max_preview_bytes - preview.size();
        }
      }
      ++absolute_offset;
    }
  }

  result.bytes_scanned = absolute_offset;
  if (!stop && have_unterminated_line) {
    finish_line();
  }
  result.file_changed_during_read =
      result.file_changed_during_read || file_size_changed(file);
  return {.result = std::move(result), .error = std::nullopt};
}

LogTailOutcome LogAnalyzer::tail(const ReadOnlyFile& file,
                                 const LogTailOptions& options,
                                 const OperationContext context) const {
  if (const auto stopped = operation_error(context)) {
    return {.result = std::nullopt, .error = stopped};
  }
  if (options.max_lines == 0U || options.max_lines > limits_.max_tail_lines ||
      limits_.max_preview_bytes == 0U || limits_.read_chunk_bytes == 0U) {
    return {.result = std::nullopt,
            .error = error(LogAnalysisErrorCode::kInvalidArguments,
                           "tail arguments are outside the accepted limits")};
  }
  if (file.observed_size() > limits_.max_scan_bytes) {
    return {.result = std::nullopt,
            .error = error(LogAnalysisErrorCode::kInputTooLarge,
                           "log file exceeds the synchronous scan limit")};
  }

  LogTailResult result;
  std::deque<LogTailLine> retained;
  const std::uint64_t read_limit =
      std::min(file.observed_size(), file.max_read_bytes());
  std::vector<unsigned char> buffer(limits_.read_chunk_bytes);
  std::deque<unsigned char> line_preview;
  std::uint64_t absolute_offset = 0U;
  std::uint64_t line_number = 1U;
  std::uint64_t line_start_offset = 0U;
  std::uint64_t line_bytes = 0U;
  bool have_unterminated_line = false;

  const auto finish_line = [&]() {
    const bool truncated_start = line_bytes > line_preview.size();
    if (!line_preview.empty() &&
        line_preview.back() == static_cast<unsigned char>('\r')) {
      line_preview.pop_back();
    }
    retained.push_back(LogTailLine{
        .line_number = line_number,
        .byte_offset = line_start_offset,
        .preview = escape_preview(line_preview),
        .preview_truncated_start = truncated_start,
    });
    if (retained.size() > options.max_lines) {
      retained.pop_front();
    }
    ++result.lines_scanned;
    ++line_number;
    line_start_offset = absolute_offset + 1U;
    line_preview.clear();
    line_bytes = 0U;
    have_unterminated_line = false;
  };

  while (absolute_offset < read_limit) {
    if (const auto stopped = operation_error(context)) {
      return {.result = std::nullopt, .error = stopped};
    }
    const std::uint64_t remaining = read_limit - absolute_offset;
    const std::size_t requested = static_cast<std::size_t>(
        std::min<std::uint64_t>(remaining, buffer.size()));
    const ssize_t count = ::pread(file.fd(), buffer.data(), requested,
                                  static_cast<off_t>(absolute_offset));
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return {.result = std::nullopt,
              .error = error(LogAnalysisErrorCode::kReadFailed,
                             "failed while reading the approved log file")};
    }
    if (count == 0) {
      result.file_changed_during_read = absolute_offset < read_limit;
      break;
    }

    const auto available = static_cast<std::size_t>(count);
    for (std::size_t index = 0U; index < available; ++index) {
      const unsigned char value = buffer[index];
      if (value == static_cast<unsigned char>('\n')) {
        finish_line();
        ++absolute_offset;
        continue;
      }
      have_unterminated_line = true;
      ++line_bytes;
      line_preview.push_back(value);
      if (line_preview.size() > limits_.max_preview_bytes) {
        line_preview.pop_front();
      }
      ++absolute_offset;
    }
  }

  result.bytes_scanned = absolute_offset;
  if (have_unterminated_line) {
    finish_line();
  }
  result.file_changed_during_read =
      result.file_changed_during_read || file_size_changed(file);
  result.lines.assign(std::make_move_iterator(retained.begin()),
                      std::make_move_iterator(retained.end()));
  return {.result = std::move(result), .error = std::nullopt};
}

const LogAnalysisLimits& LogAnalyzer::limits() const noexcept { return limits_; }

std::string_view log_analysis_error_name(
    const LogAnalysisErrorCode code) noexcept {
  switch (code) {
    case LogAnalysisErrorCode::kInvalidArguments:
      return "invalid_arguments";
    case LogAnalysisErrorCode::kInputTooLarge:
      return "input_too_large";
    case LogAnalysisErrorCode::kReadFailed:
      return "read_failed";
    case LogAnalysisErrorCode::kCancelled:
      return "cancelled";
    case LogAnalysisErrorCode::kDeadlineExceeded:
      return "deadline_exceeded";
  }
  return "unknown";
}

}  // namespace native_mcp
