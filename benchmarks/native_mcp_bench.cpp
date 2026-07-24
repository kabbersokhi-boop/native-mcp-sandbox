#include "native_mcp/elf_analysis.hpp"
#include "native_mcp/file_policy.hpp"
#include "native_mcp/json_safety.hpp"
#include "native_mcp/log_analysis.hpp"
#include "native_mcp/process_parsing.hpp"
#include "native_mcp/runtime_config.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <numeric>
#include <string>
#include <string_view>
#include <vector>

namespace {
std::atomic<std::uint64_t> benchmark_sink{0U};

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
constexpr std::size_t kSamples = 7U;
constexpr std::size_t kIterations = 100U;

template <typename Operation>
Json measure(std::string_view id, std::size_t input_bytes, Operation operation) {
  for (std::size_t index = 0; index < 10U; ++index) { benchmark_sink.fetch_add(static_cast<std::uint64_t>(operation()), std::memory_order_relaxed); }
  std::vector<double> samples;
  samples.reserve(kSamples);
  for (std::size_t sample = 0; sample < kSamples; ++sample) {
    const auto started = Clock::now();
    for (std::size_t iteration = 0; iteration < kIterations; ++iteration) { benchmark_sink.fetch_add(static_cast<std::uint64_t>(operation()), std::memory_order_relaxed); }
    const auto elapsed = std::chrono::duration<double, std::nano>(Clock::now() - started).count();
    samples.push_back(elapsed / static_cast<double>(kIterations));
  }
  std::vector<double> sorted = samples;
  std::sort(sorted.begin(), sorted.end());
  const double mean = std::accumulate(samples.begin(), samples.end(), 0.0) /
      static_cast<double>(samples.size());
  double variance = 0.0;
  for (const double value : samples) { variance += (value - mean) * (value - mean); }
  variance /= static_cast<double>(samples.size());
  return Json{{"caseId", id}, {"unit", "nanoseconds_per_operation"},
      {"inputBytes", input_bytes}, {"operationCount", kIterations},
      {"concurrency", 1}, {"timeoutMilliseconds", 1000},
      {"warmupIterations", 10}, {"sampleCount", samples.size()},
      {"originalSampleCount", samples.size()}, {"retainedSampleCount", samples.size()},
      {"excludedSampleCount", 0}, {"exclusionClasses", Json::array()},
      {"rawSamples", samples}, {"minimum", sorted.front()}, {"maximum", sorted.back()},
      {"median", sorted[sorted.size() / 2U]}, {"p95", sorted[(sorted.size() * 95U) / 100U]},
      {"mean", mean}, {"standardDeviation", std::sqrt(variance)},
      {"validationInTimedRegion", true}, {"optimizationSink", benchmark_sink.load(std::memory_order_relaxed)}};
}

void require(bool condition, std::string_view message) {
  if (!condition) { throw std::runtime_error(std::string(message)); }
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc != 2) { std::cerr << "usage: native_mcp_bench FIXTURE_DIRECTORY\n"; return EXIT_FAILURE; }
    const std::filesystem::path fixtures = argv[1];
    const std::string valid = R"({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})";
    const std::string rejected = R"({"jsonrpc":"2.0","id":1,"id":2})";
    const std::string config = "{\"version\":2,\"roots\":[{\"name\":\"fixtures\",\"path\":\"" +
        fixtures.string() + "\",\"maxFileBytes\":65536}],\"processes\":[{\"name\":\"server\",\"pid\":\"self\"}]}";
    native_mcp::FilesystemPolicyConfig policy_config{{{"fixtures", fixtures.string(), 65536U}}};
    auto policy = native_mcp::FilesystemPolicy::create(policy_config);
    native_mcp::LogAnalyzer logs;
    native_mcp::ElfAnalyzer elf;
    const std::string stat = "fixture-process (worker) S 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 4242 0 0\n";
    const std::string status = "Name:\tfixture-process\nState:\tS (sleeping)\nUid:\t1000\t1000\t1000\t1000\nThreads:\t2\nVmRSS:\t12 kB\nRssAnon:\t4 kB\nRssFile:\t8 kB\n";
    Json cases = Json::array();
    cases.push_back(measure("component.json_sax.valid", valid.size(), [&] { require(native_mcp::preflight_json(valid) == native_mcp::JsonPreflightStatus::kOk, "preflight"); return 1U; }));
    cases.push_back(measure("component.json_sax.rejected_duplicate", rejected.size(), [&] { require(native_mcp::preflight_json(rejected) == native_mcp::JsonPreflightStatus::kDuplicateKey, "reject"); return 1U; }));
    cases.push_back(measure("component.json_dom.parse", valid.size(), [&] { const Json value = Json::parse(valid); require(value.size() == 4U && value.at("method") == "tools/list", "dom"); return value.size(); }));
    cases.push_back(measure("comparison.protocol.sax_plus_dom", valid.size(), [&] { require(native_mcp::preflight_json(valid) == native_mcp::JsonPreflightStatus::kOk, "preflight"); const Json value = Json::parse(valid); require(value.at("method") == "tools/list" && value.size() == 4U, "equivalent dom"); return value.size(); }));
    cases.push_back(measure("component.runtime_policy.parse", config.size(), [&] { require(native_mcp::parse_runtime_policy_config(config).config.has_value(), "policy"); return 1U; }));
    cases.push_back(measure("component.proc_text.parse", stat.size() + status.size(), [&] { require(native_mcp::process_parsing::parse_stat_identity_text(stat).has_value() && native_mcp::process_parsing::parse_status_text(status).has_value(), "proc"); return 1U; }));
    Json omitted = Json::array();
    if (policy.policy.has_value()) {
      cases.push_back(measure("component.logs.search.streaming", 56U, [&] { auto opened = policy.policy->open_regular_file("fixtures", "log.txt"); require(opened.file.has_value(), "open log"); auto result = logs.search(*opened.file, {.query="needle", .case_sensitive=true, .max_matches=10U}); require(result.result.has_value() && result.result->matches.size() == 3U, "search"); return result.result->matches.size(); }));
      cases.push_back(measure("component.logs.tail.streaming", 56U, [&] { auto opened = policy.policy->open_regular_file("fixtures", "log.txt"); require(opened.file.has_value(), "open log"); auto result = logs.tail(*opened.file, {.max_lines=2U}); require(result.result.has_value() && result.result->lines.size() == 2U, "tail"); return result.result->lines.size(); }));
      cases.push_back(measure("component.elf.inspect", 64U, [&] { auto opened = policy.policy->open_regular_file("fixtures", "minimal.elf"); require(opened.file.has_value(), "open elf"); auto result = elf.inspect(*opened.file); require(result.result.has_value() && result.result->elf_class == "ELF64", "elf"); return result.result->program_header_count; }));
    } else { omitted.push_back("log and ELF component cases require strict openat2, unavailable on this host"); }
    std::cout << Json{{"harnessVersion", "1.0.0"}, {"framework", { {"name", "project-owned-cpp"}, {"version", "1.0.0"} }}, {"cases", cases}, {"omitted", omitted}}.dump() << '\n';
  } catch (const std::exception& error) { std::cerr << "benchmark failure: " << error.what() << '\n'; return EXIT_FAILURE; }
  return EXIT_SUCCESS;
}
