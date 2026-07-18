#include "native_mcp/orchestration.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using namespace std::chrono_literals;
using native_mcp::OperationContext;
using native_mcp::ResourceBudget;
using native_mcp::ScheduledToolCall;
using native_mcp::ToolExecutionResult;
using native_mcp::ToolScheduler;
using native_mcp::ToolSubmitStatus;
using Json = nlohmann::json;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

ToolExecutionResult success(const std::string& value) {
  return {.is_error = false, .structured_content = Json{{"value", value}}};
}

ResourceBudget budget(const std::size_t pending = 4U,
                      const std::size_t workers = 2U,
                      const std::uint32_t timeout_ms = 1000U) {
  return ResourceBudget{.max_request_bytes = 4096U,
                        .max_response_bytes = 4096U,
                        .max_pending_requests = pending,
                        .worker_threads = workers,
                        .operation_timeout_ms = timeout_ms};
}

void test_parallel_execution_and_completion() {
  std::mutex mutex;
  std::condition_variable cv;
  std::vector<int> completed;
  std::atomic<int> active{0};
  std::atomic<int> maximum_active{0};

  ToolScheduler scheduler{
      budget(),
      [&](std::string_view, const Json& arguments, const OperationContext&) {
        const int now = active.fetch_add(1) + 1;
        int observed = maximum_active.load();
        while (observed < now &&
               !maximum_active.compare_exchange_weak(observed, now)) {
        }
        std::this_thread::sleep_for(40ms);
        active.fetch_sub(1);
        return success(arguments.at("value").get<std::string>());
      },
      [&](const Json& id, ToolExecutionResult result) {
        expect(!result.is_error, "parallel result must succeed");
        {
          std::lock_guard lock{mutex};
          completed.push_back(id.get<int>());
        }
        cv.notify_all();
      }};

  expect(scheduler.submit({1, "test", Json{{"value", "one"}}}) ==
             ToolSubmitStatus::kAccepted,
         "first call must be accepted");
  expect(scheduler.submit({2, "test", Json{{"value", "two"}}}) ==
             ToolSubmitStatus::kAccepted,
         "second call must be accepted");
  {
    std::unique_lock lock{mutex};
    expect(cv.wait_for(lock, 2s, [&] { return completed.size() == 2U; }),
           "parallel calls must complete");
  }
  scheduler.shutdown();
  expect(maximum_active.load() >= 2, "two workers must execute concurrently");
  const auto stats = scheduler.stats();
  expect(stats.accepted == 2U && stats.completed == 2U &&
             stats.outstanding == 0U,
         "completion statistics must be exact");
}

void test_queue_and_duplicate_rejection() {
  std::mutex gate_mutex;
  std::condition_variable gate_cv;
  bool release = false;
  ToolScheduler scheduler{
      budget(1U, 1U),
      [&](std::string_view, const Json&, const OperationContext&) {
        std::unique_lock lock{gate_mutex};
        gate_cv.wait(lock, [&] { return release; });
        return success("done");
      },
      [](const Json&, ToolExecutionResult) {}};

  expect(scheduler.submit({"a", "test", Json::object()}) ==
             ToolSubmitStatus::kAccepted,
         "first bounded call must be accepted");
  expect(scheduler.submit({"a", "test", Json::object()}) ==
             ToolSubmitStatus::kDuplicateRequestId,
         "duplicate in-flight id must be rejected");
  expect(scheduler.submit({"b", "test", Json::object()}) ==
             ToolSubmitStatus::kQueueFull,
         "full outstanding budget must reject new work");
  {
    std::lock_guard lock{gate_mutex};
    release = true;
  }
  gate_cv.notify_all();
  scheduler.shutdown();
  const auto stats = scheduler.stats();
  expect(stats.queue_rejections == 1U && stats.duplicate_rejections == 1U,
         "rejection statistics must be exact");
}

void test_cancellation_suppresses_response() {
  std::mutex mutex;
  std::condition_variable cv;
  bool started = false;
  std::atomic<int> completions{0};
  ToolScheduler scheduler{
      budget(),
      [&](std::string_view, const Json&, const OperationContext& context) {
        {
          std::lock_guard lock{mutex};
          started = true;
        }
        cv.notify_all();
        while (!context.should_stop()) {
          std::this_thread::sleep_for(1ms);
        }
        return ToolExecutionResult{.is_error = true,
                                   .structured_content = Json{{"error", "stopped"}}};
      },
      [&](const Json&, ToolExecutionResult) { completions.fetch_add(1); }};

  expect(scheduler.submit({7, "test", Json::object()}) ==
             ToolSubmitStatus::kAccepted,
         "cancellable call must be accepted");
  {
    std::unique_lock lock{mutex};
    expect(cv.wait_for(lock, 1s, [&] { return started; }),
           "cancellable call must start");
  }
  expect(scheduler.cancel(7), "known request must be cancellable");
  scheduler.shutdown();
  expect(completions.load() == 0,
         "client cancellation must suppress the normal response");
  expect(scheduler.stats().cancelled == 1U,
         "cancellation must be recorded");
}

void test_deadline_error() {
  std::mutex mutex;
  std::condition_variable cv;
  bool completed = false;
  ToolExecutionResult observed;
  ToolScheduler scheduler{
      budget(2U, 1U, 20U),
      [](std::string_view, const Json&, const OperationContext& context) {
        while (!context.should_stop()) {
          std::this_thread::sleep_for(1ms);
        }
        return success("late");
      },
      [&](const Json&, ToolExecutionResult result) {
        {
          std::lock_guard lock{mutex};
          observed = std::move(result);
          completed = true;
        }
        cv.notify_all();
      }};
  expect(scheduler.submit({9, "test", Json::object()}) ==
             ToolSubmitStatus::kAccepted,
         "deadline call must be accepted");
  {
    std::unique_lock lock{mutex};
    expect(cv.wait_for(lock, 1s, [&] { return completed; }),
           "deadline result must be delivered");
  }
  scheduler.shutdown();
  expect(observed.is_error &&
             observed.structured_content["error"]["code"] ==
                 "deadline_exceeded",
         "deadline must become a bounded execution error");
  expect(scheduler.stats().timed_out == 1U,
         "deadline must be recorded");
}

void test_invalid_budget_uses_conservative_scheduler_limits() {
  std::mutex mutex;
  std::condition_variable cv;
  bool completed = false;
  ResourceBudget invalid = budget();
  invalid.worker_threads = 0U;

  ToolScheduler scheduler{
      invalid,
      [](std::string_view, const Json&, const OperationContext&) {
        return success("completed");
      },
      [&](const Json&, ToolExecutionResult result) {
        expect(!result.is_error, "normalized scheduler call must succeed");
        {
          std::lock_guard lock{mutex};
          completed = true;
        }
        cv.notify_all();
      }};

  expect(scheduler.submit({"invalid-budget", "test", Json::object()}) ==
             ToolSubmitStatus::kAccepted,
         "invalid scheduler budgets must not leave accepted work undrainable");
  {
    std::unique_lock lock{mutex};
    expect(cv.wait_for(lock, 1s, [&] { return completed; }),
           "normalized scheduler budget must provide workers");
  }
  scheduler.shutdown();
}

}  // namespace

int main() {
  test_parallel_execution_and_completion();
  test_queue_and_duplicate_rejection();
  test_cancellation_suppresses_response();
  test_deadline_error();
  test_invalid_budget_uses_conservative_scheduler_limits();
  std::cout << "All orchestration tests passed\n";
  return EXIT_SUCCESS;
}
