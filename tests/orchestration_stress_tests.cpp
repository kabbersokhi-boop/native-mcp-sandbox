#include "native_mcp/orchestration.hpp"

#include <nlohmann/json.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using namespace std::chrono_literals;
using Json = nlohmann::json;
using native_mcp::OperationContext;
using native_mcp::ResourceBudget;
using native_mcp::ScheduledToolCall;
using native_mcp::ToolExecutionResult;
using native_mcp::ToolScheduler;
using native_mcp::ToolSubmitStatus;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

[[nodiscard]] ToolExecutionResult success() {
  return {.is_error = false, .structured_content = Json{{"ok", true}}};
}

[[nodiscard]] ResourceBudget budget(const std::uint32_t timeout_ms = 1000U) {
  return ResourceBudget{.max_request_bytes = 4096U,
                        .max_response_bytes = 4096U,
                        .max_pending_requests = 16U,
                        .worker_threads = 2U,
                        .operation_timeout_ms = timeout_ms};
}

void test_parallel_admission_cancellation_and_shutdown_stress() {
  constexpr int kRounds = 100;
  constexpr int kCalls = 16;
  constexpr int kCancelled = 6;
  for (int round = 0; round < kRounds; ++round) {
    std::atomic<bool> release{false};
    std::atomic<int> completions{0};
    ToolScheduler scheduler{
        budget(),
        [&](std::string_view, const Json&, const OperationContext& context) {
          while (!release.load(std::memory_order_acquire) &&
                 !context.should_stop()) {
            std::this_thread::yield();
          }
          return success();
        },
        [&](const Json&, ToolExecutionResult result) {
          expect(!result.is_error, "non-cancelled stress calls must succeed");
          completions.fetch_add(1, std::memory_order_relaxed);
        }};

    std::atomic<int> accepted{0};
    std::vector<std::thread> producers;
    for (int producer = 0; producer < 4; ++producer) {
      producers.emplace_back([&, producer] {
        for (int offset = 0; offset < 4; ++offset) {
          const int id = round * kCalls + producer * 4 + offset;
          if (scheduler.submit(
                  ScheduledToolCall{id, "stress", Json::object()}) ==
              ToolSubmitStatus::kAccepted) {
            accepted.fetch_add(1, std::memory_order_relaxed);
          }
        }
      });
    }
    for (std::thread& producer : producers) {
      producer.join();
    }
    expect(accepted.load() == kCalls,
           "all bounded concurrent submissions must be accepted");

    for (int offset = 0; offset < kCalls; offset += 3) {
      const int id = round * kCalls + offset;
      expect(scheduler.cancel(id),
             "queued or running stress request must be cancellable");
    }
    release.store(true, std::memory_order_release);

    std::vector<std::thread> shutdown_callers;
    for (int index = 0; index < 3; ++index) {
      shutdown_callers.emplace_back([&] { scheduler.shutdown(); });
    }
    for (std::thread& caller : shutdown_callers) {
      caller.join();
    }

    const auto stats = scheduler.stats();
    expect(stats.accepted == static_cast<std::size_t>(kCalls),
           "accepted statistic must remain exact under contention");
    expect(stats.cancelled == static_cast<std::size_t>(kCancelled),
           "cancelled statistic must remain exact under contention");
    expect(stats.completed ==
               static_cast<std::size_t>(kCalls - kCancelled),
           "completion statistic must exclude suppressed cancellations");
    expect(stats.outstanding == 0U && stats.queued == 0U,
           "stress shutdown must drain all scheduler state");
    expect(completions.load() == kCalls - kCancelled,
           "completion callback count must match scheduler statistics");
  }
}

void test_cancellation_deadline_precedence_stress() {
  constexpr int kCalls = 200;
  std::mutex mutex;
  std::condition_variable cv;
  int completions = 0;
  ToolScheduler scheduler{
      budget(5U),
      [](std::string_view, const Json&, const OperationContext& context) {
        while (!context.should_stop()) {
          std::this_thread::yield();
        }
        return success();
      },
      [&](const Json&, ToolExecutionResult result) {
        expect(result.is_error,
               "deadline-driven stress completions must be bounded errors");
        {
          std::lock_guard lock{mutex};
          ++completions;
        }
        cv.notify_all();
      }};

  for (int id = 0; id < kCalls; ++id) {
    expect(scheduler.submit({id, "deadline", Json::object()}) ==
               ToolSubmitStatus::kAccepted,
           "serial stress request must be accepted");
    if ((id & 1) == 0) {
      expect(scheduler.cancel(id),
             "even stress requests must be cancelled before completion");
      const auto wait_until = std::chrono::steady_clock::now() + 1s;
      while (scheduler.stats().outstanding != 0U &&
             std::chrono::steady_clock::now() < wait_until) {
        std::this_thread::sleep_for(1ms);
      }
      expect(scheduler.stats().outstanding == 0U,
             "cancelled stress request must leave the scheduler promptly");
    } else {
      std::unique_lock lock{mutex};
      const int expected = (id + 1) / 2;
      expect(cv.wait_for(lock, 1s, [&] { return completions >= expected; }),
             "odd stress request must reach its deadline");
    }
  }
  scheduler.shutdown();
  const auto stats = scheduler.stats();
  expect(stats.cancelled == 100U,
         "client cancellation must win for all explicitly cancelled calls");
  expect(stats.timed_out == 100U && stats.completed == 100U,
         "uncancelled calls must produce deadline errors");
  expect(completions == 100,
         "cancelled calls must never invoke the completion callback");
}

void test_throwing_completion_does_not_kill_workers() {
  std::atomic<int> executions{0};
  ToolScheduler scheduler{
      budget(),
      [&](std::string_view, const Json&, const OperationContext&) {
        executions.fetch_add(1, std::memory_order_relaxed);
        return success();
      },
      [](const Json&, ToolExecutionResult) {
        throw 42;
      }};
  for (int id = 0; id < 16; ++id) {
    expect(scheduler.submit({id, "throwing-completion", Json::object()}) ==
               ToolSubmitStatus::kAccepted,
           "throwing callback stress requests must be accepted");
  }
  scheduler.shutdown();
  expect(executions.load() == 16,
         "completion exceptions must not terminate or poison workers");
  expect(scheduler.stats().completed == 16U,
         "completion exceptions must not corrupt scheduler accounting");
}

void test_worker_callback_shutdown_stress() {
  constexpr int kRounds = 250;
  for (int round = 0; round < kRounds; ++round) {
    std::atomic<int> executing{0};
    std::atomic<int> callbacks_ready{0};
    std::atomic<int> shutdown_returns{0};
    ToolScheduler* scheduler_ptr = nullptr;
    ToolScheduler scheduler{
        budget(),
        [&](std::string_view, const Json&, const OperationContext&) {
          executing.fetch_add(1, std::memory_order_acq_rel);
          while (executing.load(std::memory_order_acquire) != 2) {
            std::this_thread::yield();
          }
          return success();
        },
        [&](const Json&, ToolExecutionResult result) {
          expect(!result.is_error,
                 "callback shutdown stress work must succeed");
          callbacks_ready.fetch_add(1, std::memory_order_acq_rel);
          while (callbacks_ready.load(std::memory_order_acquire) != 2) {
            std::this_thread::yield();
          }
          scheduler_ptr->shutdown();
          shutdown_returns.fetch_add(1, std::memory_order_acq_rel);
        }};
    scheduler_ptr = &scheduler;

    expect(scheduler.submit({round * 2, "callback-shutdown", Json::object()}) ==
               ToolSubmitStatus::kAccepted,
           "first callback shutdown stress request must be accepted");
    expect(scheduler.submit({round * 2 + 1, "callback-shutdown", Json::object()}) ==
               ToolSubmitStatus::kAccepted,
           "second callback shutdown stress request must be accepted");

    const auto deadline = std::chrono::steady_clock::now() + 2s;
    while (shutdown_returns.load(std::memory_order_acquire) != 2 &&
           std::chrono::steady_clock::now() < deadline) {
      std::this_thread::yield();
    }
    expect(shutdown_returns.load(std::memory_order_acquire) == 2,
           "both callback shutdown calls must return in every stress round");
    scheduler.shutdown();
    expect(scheduler.stats().completed == 2U &&
               scheduler.stats().outstanding == 0U,
           "callback shutdown stress must drain and join exactly");
  }
}

}  // namespace

int main() {
  test_parallel_admission_cancellation_and_shutdown_stress();
  test_cancellation_deadline_precedence_stress();
  test_throwing_completion_does_not_kill_workers();
  test_worker_callback_shutdown_stress();
  std::cout << "All orchestration stress tests passed\n";
  return EXIT_SUCCESS;
}
