#include "native_mcp/log_analysis.hpp"

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <stop_token>

namespace {

namespace fs = std::filesystem;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

class TempDirectory final {
 public:
  TempDirectory() {
    std::string pattern = "/tmp/native-mcp-logs-XXXXXX";
    pattern.push_back('\0');
    char* created = ::mkdtemp(pattern.data());
    expect(created != nullptr, "failed to create temporary directory");
    path_ = created;
  }
  ~TempDirectory() {
    std::error_code ignored;
    fs::remove_all(path_, ignored);
  }
  TempDirectory(const TempDirectory&) = delete;
  TempDirectory& operator=(const TempDirectory&) = delete;
  [[nodiscard]] const fs::path& path() const noexcept { return path_; }

 private:
  fs::path path_;
};

void write_bytes(const fs::path& path, const std::string& bytes) {
  std::ofstream output(path, std::ios::binary);
  expect(static_cast<bool>(output), "failed to create log fixture");
  output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  expect(static_cast<bool>(output), "failed to write log fixture");
}

native_mcp::ReadOnlyFile open_read_only(const fs::path& path,
                                        const std::uint64_t max_read_bytes) {
  native_mcp::UniqueFd fd{::open(path.c_str(), O_RDONLY | O_CLOEXEC)};
  expect(fd.valid(), "failed to open log fixture");
  struct stat metadata {};
  expect(::fstat(fd.get(), &metadata) == 0 && metadata.st_size >= 0,
         "failed to inspect log fixture");
  return native_mcp::ReadOnlyFile{
      std::move(fd), static_cast<std::uint64_t>(metadata.st_size),
      max_read_bytes};
}

void test_literal_search() {
  TempDirectory directory;
  const fs::path path = directory.path() / "app.log";
  const std::string text =
      "INFO ready\nError first and error repeated\nwarning\nERROR second\n";
  write_bytes(path, text);
  auto file = open_read_only(path, text.size());

  native_mcp::LogAnalysisLimits limits;
  limits.read_chunk_bytes = 5U;
  native_mcp::LogAnalyzer analyzer{limits};
  auto outcome = analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "error",
                                         .case_sensitive = false,
                                         .max_matches = 10U});
  expect(outcome.result.has_value(), "valid log search must succeed");
  expect(outcome.result->matches.size() == 2U,
         "ASCII-insensitive search must find two lines");
  expect(outcome.result->matches[0].line_number == 2U &&
             outcome.result->matches[1].line_number == 4U,
         "search must report deterministic line numbers");
  expect(outcome.result->matches[0].byte_offset == 11U,
         "search must report the first match byte offset");
  expect(outcome.result->bytes_scanned == text.size() &&
             outcome.result->lines_scanned == 4U,
         "complete bounded scan must report bytes and lines");
  expect(!outcome.result->match_limit_reached,
         "unreached match limit must remain false");
}

void test_chunk_boundary_and_long_line_preview() {
  TempDirectory directory;
  const fs::path path = directory.path() / "long.log";
  const std::string text = std::string(1000U, 'a') + "needle" +
                           std::string(100U, 'z') + "\n";
  write_bytes(path, text);
  auto file = open_read_only(path, text.size());

  native_mcp::LogAnalysisLimits limits;
  limits.read_chunk_bytes = 4U;
  limits.max_preview_bytes = 32U;
  native_mcp::LogAnalyzer analyzer{limits};
  auto outcome = analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "needle",
                                         .case_sensitive = true,
                                         .max_matches = 5U});
  expect(outcome.result.has_value() &&
             outcome.result->matches.size() == 1U,
         "query spanning read chunks must be found");
  const auto& match = outcome.result->matches.front();
  expect(match.preview.find("needle") != std::string::npos,
         "bounded preview must include the match");
  expect(match.preview_truncated_start && match.preview_truncated_end,
         "long line preview must disclose both truncation directions");
}

void test_binary_preview_escaping() {
  TempDirectory directory;
  const fs::path path = directory.path() / "binary.log";
  std::string text{"ok "};
  text.push_back('\x01');
  text += " ERROR ";
  text.push_back(static_cast<char>(0xFF));
  text.push_back('\n');
  write_bytes(path, text);
  auto file = open_read_only(path, text.size());

  native_mcp::LogAnalyzer analyzer;
  auto outcome = analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "ERROR",
                                         .case_sensitive = true,
                                         .max_matches = 5U});
  expect(outcome.result.has_value() &&
             outcome.result->matches.size() == 1U,
         "binary-containing log line must remain searchable");
  const std::string& preview = outcome.result->matches.front().preview;
  expect(preview.find("\\x01") != std::string::npos &&
             preview.find("\\xFF") != std::string::npos,
         "non-text bytes must be escaped in model-facing output");
}

void test_match_limit_stops_scan() {
  TempDirectory directory;
  const fs::path path = directory.path() / "many.log";
  const std::string text = "error one\nerror two\nerror three\n";
  write_bytes(path, text);
  auto file = open_read_only(path, text.size());

  native_mcp::LogAnalyzer analyzer;
  auto outcome = analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "error",
                                         .case_sensitive = true,
                                         .max_matches = 2U});
  expect(outcome.result.has_value() &&
             outcome.result->matches.size() == 2U,
         "search must honor the requested match bound");
  expect(outcome.result->match_limit_reached,
         "early stop must be disclosed");
  expect(outcome.result->bytes_scanned < text.size(),
         "match bound must stop further file scanning");
}

void test_tail_and_long_line_retention() {
  TempDirectory directory;
  const fs::path path = directory.path() / "tail.log";
  const std::string long_line = std::string(40U, 'x') + "END";
  const std::string text = "one\ntwo\nthree\nfour\n" + long_line;
  write_bytes(path, text);
  auto file = open_read_only(path, text.size());

  native_mcp::LogAnalysisLimits limits;
  limits.read_chunk_bytes = 3U;
  limits.max_preview_bytes = 16U;
  native_mcp::LogAnalyzer analyzer{limits};
  auto outcome = analyzer.tail(
      file, native_mcp::LogTailOptions{.max_lines = 3U});
  expect(outcome.result.has_value() && outcome.result->lines.size() == 3U,
         "tail must retain only the requested final lines");
  expect(outcome.result->lines[0].line_number == 3U &&
             outcome.result->lines[2].line_number == 5U,
         "tail must preserve original line numbers");
  expect(outcome.result->lines[2].preview.find("END") !=
             std::string::npos &&
             outcome.result->lines[2].preview_truncated_start,
         "long tail lines must retain their end and disclose truncation");
}

void test_fixed_read_budget_and_argument_errors() {
  TempDirectory directory;
  const fs::path path = directory.path() / "growing.log";
  write_bytes(path, "before\n");
  auto file = open_read_only(path, 1024U);
  {
    std::ofstream output(path, std::ios::binary | std::ios::app);
    output << "secret-after-open\n";
  }

  native_mcp::LogAnalyzer analyzer;
  auto searched = analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "secret",
                                         .case_sensitive = true,
                                         .max_matches = 5U});
  expect(searched.result.has_value() && searched.result->matches.empty(),
         "file growth must not expand the fixed observed read budget");
  expect(searched.result->file_changed_during_read,
         "file-size changes must be disclosed");

  searched = analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "bad\nquery",
                                         .case_sensitive = true,
                                         .max_matches = 5U});
  expect(searched.error.has_value() &&
             searched.error->code ==
                 native_mcp::LogAnalysisErrorCode::kInvalidArguments,
         "multiline search queries must be rejected");

  native_mcp::LogAnalysisLimits tiny;
  tiny.max_scan_bytes = 2U;
  native_mcp::LogAnalyzer tiny_analyzer{tiny};
  searched = tiny_analyzer.search(
      file, native_mcp::LogSearchOptions{.query = "b",
                                         .case_sensitive = true,
                                         .max_matches = 1U});
  expect(searched.error.has_value() &&
             searched.error->code ==
                 native_mcp::LogAnalysisErrorCode::kInputTooLarge,
         "files above the synchronous scan cap must fail closed");
}

}  // namespace

void test_operation_stop_context() {
  TempDirectory directory;
  const fs::path path = directory.path() / "cancel.log";
  write_bytes(path, "one\ntwo\n");
  auto file = open_read_only(path, 8U);
  std::stop_source source;
  (void)source.request_stop();
  const native_mcp::OperationContext cancelled{
      source.get_token(), native_mcp::OperationContext::Clock::time_point::max()};
  const auto searched = native_mcp::LogAnalyzer{}.search(
      file, native_mcp::LogSearchOptions{.query = "one"}, cancelled);
  expect(searched.error.has_value() &&
             searched.error->code == native_mcp::LogAnalysisErrorCode::kCancelled,
         "log analysis must honor cooperative cancellation before reading");
}

int main() {
  test_literal_search();
  test_chunk_boundary_and_long_line_preview();
  test_binary_preview_escaping();
  test_match_limit_stops_scan();
  test_tail_and_long_line_retention();
  test_fixed_read_budget_and_argument_errors();
  test_operation_stop_context();
  std::cout << "All log analysis tests passed\n";
  return EXIT_SUCCESS;
}
