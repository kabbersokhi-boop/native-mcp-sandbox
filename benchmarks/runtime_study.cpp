#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <nlohmann/json.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "native_mcp/elf_analysis.hpp"
#include "native_mcp/file_policy.hpp"
#include "native_mcp/json_safety.hpp"
#include "native_mcp/log_analysis.hpp"
#include "native_mcp/orchestration.hpp"
#include "native_mcp/process_memory.hpp"

namespace {

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;

void require(const bool accepted, const std::string& message) {
  if (!accepted) {
    throw std::runtime_error(message);
  }
}

std::size_t entries(const std::string& path) {
  std::size_t count = 0;
  for (const auto& entry : std::filesystem::directory_iterator(path)) {
    (void)entry;
    ++count;
  }
  return count;
}

template <typename Operation>
Json measure(const std::string& name, const int samples, Operation operation) {
  for (int warmup = 0; warmup < 3; ++warmup) {
    operation();
  }
  std::vector<double> elapsed;
  elapsed.reserve(static_cast<std::size_t>(samples));
  for (int sample = 0; sample < samples; ++sample) {
    const auto start = Clock::now();
    operation();
    elapsed.push_back(std::chrono::duration<double, std::nano>(Clock::now() - start).count());
  }
  auto sorted = elapsed;
  std::sort(sorted.begin(), sorted.end());
  Json result{{"case", name},
              {"unit", "nanoseconds_per_operation"},
              {"rawSamples", elapsed},
              {"warmupIterations", 3},
              {"minimum", sorted.front()},
              {"maximum", sorted.back()},
              {"median", sorted[sorted.size() / 2]}};
  if (samples >= 100) {
    result["p95"] = sorted[(sorted.size() * 95 + 99) / 100 - 1];
  }
  return result;
}

Json scheduler_probe() {
  std::atomic<int> started{0};
  std::atomic<int> completions{0};
  native_mcp::ToolScheduler scheduler{
      native_mcp::conservative_budget(),
      [&](std::string_view, const Json&, const native_mcp::OperationContext& context) {
        started.fetch_add(1);
        while (!context.should_stop()) {
          std::this_thread::sleep_for(100us);
        }
        return native_mcp::ToolExecutionResult{false, Json::object()};
      },
      [&](const Json&, native_mcp::ToolExecutionResult) { completions.fetch_add(1); }};
  for (int request = 0; request < 16; ++request) {
    require(scheduler.submit({request, "probe", Json::object()}) ==
                native_mcp::ToolSubmitStatus::kAccepted,
            "scheduler did not admit the documented capacity");
  }
  require(
      scheduler.submit({16, "probe", Json::object()}) == native_mcp::ToolSubmitStatus::kQueueFull,
      "scheduler exceeded its admission limit");
  const auto deadline = Clock::now() + 1s;
  while (started.load() < 2 && Clock::now() < deadline) {
    std::this_thread::sleep_for(100us);
  }
  require(started.load() == 2, "fixed workers did not start");
  const auto threads = entries("/proc/self/task");
  const auto descriptors = entries("/proc/self/fd");
  const auto start = Clock::now();
  scheduler.request_stop();
  scheduler.shutdown();
  const auto stop_ns = std::chrono::duration<double, std::nano>(Clock::now() - start).count();
  const auto stats = scheduler.stats();
  require(stats.cancelled == 16 && stats.outstanding == 0 && completions.load() == 0,
          "transport stop failed to cancel all work");
  require(threads == 3, "scheduler created unexpected threads");
  return Json{{"accepted", stats.accepted},          {"queueRejections", stats.queue_rejections},
              {"cancelled", stats.cancelled},        {"threadsWithWorkers", threads},
              {"descriptorsWithProbe", descriptors}, {"stopAndJoinNs", stop_ns}};
}

}  // namespace

int main(int argc, char** argv) {
  try {
    require(argc == 4, "usage: native_mcp_runtime_study FIXTURE_DIRECTORY LOG_NAME SAMPLES");
    const auto fixtures = std::filesystem::canonical(argv[1]);
    const std::string log_name{argv[2]};
    const int samples = std::stoi(argv[3]);
    require(samples >= 5 && samples <= 1000, "samples must be between 5 and 1000");
    auto policy = native_mcp::FilesystemPolicy::create(
        {{{"fixtures", fixtures.string(), 16U * 1024U * 1024U}}});
    require(policy.policy.has_value(), "strict openat2 is required");
    auto processes = native_mcp::ProcessPolicy::create({{{"self", std::nullopt}}});
    require(processes.policy.has_value(), "strict pidfd is required");
    native_mcp::LogAnalyzer logs;
    native_mcp::ElfAnalyzer elf;
    Json results = Json::array();
    const auto descriptors_before = entries("/proc/self/fd");
    results.push_back(measure("logs.search.no-match", samples, [&] {
      auto opened = policy.policy->open_regular_file("fixtures", log_name);
      require(opened.file.has_value(), "log fixture unavailable");
      auto result = logs.search(*opened.file, {.query = "ABSENT_SENTINEL"});
      require(result.result.has_value() && result.result->matches.empty(), "search mismatch");
      require(result.result->bytes_scanned == opened.file->observed_size(), "incomplete scan");
    }));
    results.push_back(measure("logs.search.matching", samples, [&] {
      auto opened = policy.policy->open_regular_file("fixtures", log_name);
      require(opened.file.has_value(), "log fixture unavailable");
      auto result = logs.search(*opened.file, {.query = "needle", .max_matches = 10});
      require(result.result.has_value() && !result.result->matches.empty(), "match mismatch");
    }));
    results.push_back(measure("logs.tail", samples, [&] {
      auto opened = policy.policy->open_regular_file("fixtures", log_name);
      require(opened.file.has_value(), "log fixture unavailable");
      auto result = logs.tail(*opened.file, {.max_lines = 10});
      require(result.result.has_value() && !result.result->lines.empty(), "tail mismatch");
    }));
    results.push_back(measure("elf.inspect", samples, [&] {
      auto opened = policy.policy->open_regular_file("fixtures", "sample.elf");
      require(opened.file.has_value(), "ELF fixture unavailable");
      auto result = elf.inspect(*opened.file);
      require(result.result.has_value() && result.result->machine_number == 62, "ELF mismatch");
    }));
    results.push_back(measure("proc.memory", samples, [&] {
      auto result = processes.policy->inspect_memory("self");
      require(result.result.has_value() && result.result->pidfd_pinned,
              "process identity mismatch");
    }));
    const std::string message = R"({"jsonrpc":"2.0","id":1,"method":"ping"})";
    results.push_back(measure("json.dom-only.measurement-reference", samples, [&] {
      require(Json::parse(message).at("method") == "ping", "DOM result mismatch");
    }));
    results.push_back(measure("json.preflight-plus-dom", samples, [&] {
      require(native_mcp::preflight_json(message) == native_mcp::JsonPreflightStatus::kOk,
              "preflight result mismatch");
      require(Json::parse(message).at("method") == "ping", "DOM result mismatch");
    }));
    const auto descriptors_after = entries("/proc/self/fd");
    require(descriptors_before == descriptors_after, "descriptor growth across component samples");
    const auto scheduler = scheduler_probe();
    const auto memory = processes.policy->inspect_memory("self");
    require(memory.result.has_value() && memory.result->status.vm_hwm_bytes.has_value(),
            "procfs high-water RSS unavailable");
    std::cout << Json{{"schemaVersion", 1},
                      {"log", log_name},
                      {"samples", samples},
                      {"inputBytes", std::filesystem::file_size(fixtures / log_name)},
                      {"compiler", __VERSION__},
                      {"cases", results},
                      {"scheduler", scheduler},
                      {"peakRssBytes", *memory.result->status.vm_hwm_bytes},
                      {"memorySource", "procfs VmHWM for this executable"},
                      {"descriptorsBefore", descriptors_before},
                      {"descriptorsAfter", descriptors_after},
                      {"threadsAfterJoin", entries("/proc/self/task")}}
                     .dump()
              << '\n';
    return EXIT_SUCCESS;
  } catch (const std::exception& error) {
    std::cerr << "runtime study failed: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
