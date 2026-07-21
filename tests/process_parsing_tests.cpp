#include "native_mcp/process_parsing.hpp"

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>
#include <string_view>

namespace {

using native_mcp::process_parsing::parse_smaps_rollup_text;
using native_mcp::process_parsing::parse_stat_identity_text;
using native_mcp::process_parsing::parse_statm_text;
using native_mcp::process_parsing::parse_status_text;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

void test_stat_identity_parser() {
  const auto parsed = parse_stat_identity_text(
      "123 (checkout worker (blue)) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 "
      "16 17 18 4242 0\n");
  expect(parsed.has_value(), "valid stat identity must parse");
  expect(parsed->name == "checkout worker (blue)",
         "stat parser must preserve spaces and parentheses in comm");
  expect(parsed->state == "S" && parsed->start_time_ticks == 4242U,
         "stat parser must select state and field 22 exactly");
  expect(!parse_stat_identity_text("123 checkout S 1 2 3").has_value(),
         "stat text without a parenthesized comm must fail closed");
  expect(!parse_stat_identity_text(
              "123 (worker) SS 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 "
              "18 19")
              .has_value(),
         "multi-byte process states must be rejected");
}

void test_status_parser() {
  const auto parsed = parse_status_text(
      "Name:\tcheckout-worker\n"
      "State:\tS (sleeping)\n"
      "Uid:\t1000\t1001\t1001\t1001\n"
      "Threads:\t7\n"
      "VmRSS:\t512 kB\n"
      "RssAnon:\t128 kB\n"
      "VmSwap:\t3 kB\n");
  expect(parsed.has_value(), "valid bounded status text must parse");
  expect(parsed->name == "checkout-worker" && parsed->effective_uid == 1001U &&
             parsed->threads == 7U,
         "status parser must extract required identity fields");
  expect(parsed->memory.vm_rss_bytes == 512U * 1024U &&
             parsed->memory.rss_anon_bytes == 128U * 1024U &&
             parsed->memory.vm_swap_bytes == 3U * 1024U,
         "status parser must convert KiB counters without truncation");
  expect(!parse_status_text(
              "Name:\tworker\nState:\tR\nUid:\t1000\nThreads:\t1\n")
              .has_value(),
         "status text without an effective UID must fail closed");
  expect(!parse_status_text(
              "Name:\tworker\nState:\tR\nUid:\t0\t4294967296\t0\t0\n"
              "Threads:\t1\n")
              .has_value(),
         "effective UIDs wider than uint32 must be rejected");
  expect(!parse_status_text(
              "Name:\tworker\nState:\tR\nUid:\t0\t0\t0\t0\nThreads:\t1\n"
              "VmRSS:\t18446744073709551615 kB\n")
              .has_value(),
         "KiB multiplication overflow must fail closed");
  expect(!parse_status_text(
              "Name:\tworker\nName:\tother\nState:\tR\n"
              "Uid:\t0\t0\t0\t0\nThreads:\t1\n")
              .has_value(),
         "duplicate required status fields must fail closed");
  expect(!parse_status_text(
              "Name:\tworker\nState:\tR\nUid:\t0\t0\t0\t0\n"
              "VmRSS:\t1 kB\nIgnored:\tvalue\nVmRSS:\t2 kB\nThreads:\t1\n")
              .has_value(),
         "duplicate recognized optional status fields must fail closed");
  expect(parse_status_text(
             "Name:\tworker\nState:\tR\nUid:\t0\t0\t0\t0\n"
             "vmrss:\t1 kB\nThreads:\t1\n")
             .has_value(),
         "unknown differently cased status fields must remain ignored");
  expect(!parse_status_text(
              "Name:\tworker\nState:\tSS\nUid:\t0\t0\t0\t0\nThreads:\t1\n")
              .has_value(),
         "malformed status states must fail closed");
}

void test_statm_parser() {
  constexpr std::uint64_t kPageSize = 4096U;
  const auto parsed = parse_statm_text("100 50 10 4 0 25 0\n", kPageSize);
  expect(parsed.has_value(), "valid statm text must parse");
  expect(parsed->virtual_bytes == 100U * kPageSize &&
             parsed->resident_bytes == 50U * kPageSize &&
             parsed->shared_bytes == 10U * kPageSize &&
             parsed->text_bytes == 4U * kPageSize &&
             parsed->data_and_stack_bytes == 25U * kPageSize,
         "statm page counters must map to the documented byte fields");
  expect(!parse_statm_text("1 2 3 4 5 6", kPageSize).has_value(),
         "statm text with fewer than seven fields must fail closed");
  expect(!parse_statm_text("1 2 3 4 5 6 7 8", kPageSize).has_value(),
         "statm text with extra fields must fail closed");
  expect(parse_statm_text("1 2 3 4 5 6 7 \t\r\n", kPageSize).has_value(),
         "trailing ASCII whitespace must not create an eighth statm field");
  expect(!parse_statm_text("1 2 3 4 5 6 7x", kPageSize).has_value(),
         "statm trailing token junk must fail closed");
  const std::uint64_t overflowing_pages =
      std::numeric_limits<std::uint64_t>::max() / kPageSize + 1U;
  expect(!parse_statm_text(std::to_string(overflowing_pages) +
                               " 1 1 1 1 1 1",
                           kPageSize)
              .has_value(),
         "statm byte multiplication overflow must fail closed");
}

void test_smaps_rollup_parser() {
  const auto parsed = parse_smaps_rollup_text(
      "00400000-7fffffffffff ---p 00000000 00:00 0 [rollup]\n"
      "Rss:\t1024 kB\n"
      "Pss:\t512 kB\n"
      "Private_Dirty:\t64 kB\n"
      "Locked:\t0 kB\n");
  expect(parsed.has_value(), "recognized smaps_rollup fields must parse");
  expect(parsed->rss_bytes == 1024U * 1024U &&
             parsed->pss_bytes == 512U * 1024U &&
             parsed->private_dirty_bytes == 64U * 1024U &&
             parsed->locked_bytes == 0U,
         "smaps_rollup counters must retain exact byte values");
  expect(!parse_smaps_rollup_text("Size: 12 kB\n").has_value(),
         "smaps text without an approved aggregate field must fail closed");
  expect(!parse_smaps_rollup_text("Rss: 12 MB\n").has_value(),
         "smaps counters with unexpected units must be rejected");
  expect(!parse_smaps_rollup_text("Rss: 12 kB\nRss: 13 kB\n").has_value(),
         "duplicate smaps aggregate fields must fail closed");
  expect(!parse_smaps_rollup_text(
              "Rss: 12 kB\nIgnored: 1 kB\nRss: 13 kB\n")
              .has_value(),
         "separated duplicate smaps metrics must fail closed");
}

}  // namespace

int main() {
  test_stat_identity_parser();
  test_status_parser();
  test_statm_parser();
  test_smaps_rollup_parser();
  std::cout << "All process parser tests passed\n";
  return EXIT_SUCCESS;
}
