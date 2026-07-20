#include "native_mcp/orchestration.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <coroutine>
#include <cstdint>
#include <exception>
#include <mutex>
#include <stdexcept>
#include <stop_token>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace native_mcp {
namespace {

using Json = nlohmann::json;

[[nodiscard]] std::string request_key(const Json& request_id) {
  std::string key;
  switch (request_id.type()) {
    case Json::value_t::null:
      return "n:";
    case Json::value_t::string:
      key = "s:";
      key += request_id.get_ref<const std::string&>();
      return key;
    case Json::value_t::number_integer: {
      const auto value = request_id.get<Json::number_integer_t>();
      if (value >= 0) {
        key = "j:";
        key += std::to_string(static_cast<Json::number_unsigned_t>(value));
      } else {
        key = "i:";
        key += std::to_string(value);
      }
      return key;
    }
    case Json::value_t::number_unsigned:
      key = "j:";
      key += std::to_string(request_id.get<Json::number_unsigned_t>());
      return key;
    default:
      key = "x:";
      key += request_id.dump();
      return key;
  }
}

[[nodiscard]] std::thread default_worker_thread_factory(
    std::function<void()> callback) {
  return std::thread{std::move(callback)};
}

[[nodiscard]] ToolExecutionResult scheduler_error(
    const std::string_view code, const std::string_view message) {
  return ToolExecutionResult{
      .is_error = true,
      .structured_content =
          Json{{"error", Json{{"code", code}, {"message", message}}}},
  };
}

class DetachedTask final {
 public:
  struct promise_type final {
    [[nodiscard]] DetachedTask get_return_object() const noexcept { return {}; }
    [[nodiscard]] std::suspend_never initial_suspend() const noexcept {
      return {};
    }
    [[nodiscard]] std::suspend_never final_suspend() const noexcept { return {}; }
    void return_void() const noexcept {}
    void unhandled_exception() const noexcept { std::terminate(); }
  };
};

}  // namespace

struct ToolScheduler::Impl final {
  struct Control final {
    ScheduledToolCall call;
    std::string key;
    std::stop_source stop_source;
    OperationContext::Clock::time_point deadline;
    std::atomic<bool> cancelled_by_client{false};
  };

  struct ResumeOnWorker final {
    Impl& owner;

    [[nodiscard]] bool await_ready() const noexcept { return false; }
    void await_suspend(const std::coroutine_handle<> handle) const {
      owner.enqueue(handle);
    }
    void await_resume() const noexcept {}
  };

  Impl(const ResourceBudget resource_budget, ToolExecutor tool_executor,
       ToolCompletion tool_completion, WorkerThreadFactory worker_factory)
      : budget(is_budget_valid(resource_budget) ? resource_budget
                                                : conservative_budget()),
        executor(std::move(tool_executor)),
        completion(std::move(tool_completion)) {
    ready.reserve(budget.max_pending_requests);
    workers.reserve(budget.worker_threads);
    try {
      for (std::size_t index = 0U; index < budget.worker_threads; ++index) {
        std::thread worker = worker_factory([this] { worker_loop(); });
        if (!worker.joinable()) {
          throw std::runtime_error("worker factory returned a non-joinable thread");
        }
        workers.emplace_back(std::move(worker));
      }
    } catch (...) {
      {
        std::lock_guard lock{mutex};
        accepting = false;
        stopping = true;
      }
      ready_cv.notify_all();
      for (std::thread& worker : workers) {
        if (worker.joinable()) {
          worker.join();
        }
      }
      joined = true;
      throw;
    }
  }

  ~Impl() { shutdown(); }

  void enqueue(const std::coroutine_handle<> handle) noexcept {
    {
      std::lock_guard lock{mutex};
      ready.push_back(handle);
    }
    ready_cv.notify_one();
  }

  void worker_loop() {
    while (true) {
      std::coroutine_handle<> handle;
      {
        std::unique_lock lock{mutex};
        ready_cv.wait(lock, [this] { return stopping || !ready.empty(); });
        if (stopping && ready.empty()) {
          return;
        }
        handle = ready.front();
        ready.erase(ready.begin());
      }
      handle.resume();
    }
  }

  DetachedTask run(std::shared_ptr<Control> control) {
    co_await ResumeOnWorker{*this};

    OperationContext context{control->stop_source.get_token(), control->deadline};
    ToolExecutionResult result = scheduler_error(
        "internal_error", "tool execution failed before producing a result");
    bool have_result = false;
    bool timed_out = false;

    if (!control->cancelled_by_client.load(std::memory_order_acquire)) {
      if (context.deadline_exceeded()) {
        timed_out = true;
        result = scheduler_error("deadline_exceeded",
                                 "tool execution exceeded its deadline");
        have_result = true;
      } else {
        try {
          result = executor(control->call.name, control->call.arguments, context);
          have_result = true;
        } catch (const std::exception&) {
          result = scheduler_error("internal_error",
                                   "tool execution raised an internal exception");
          have_result = true;
        } catch (...) {
          result = scheduler_error("internal_error",
                                   "tool execution raised an unknown exception");
          have_result = true;
        }
        if (!control->cancelled_by_client.load(std::memory_order_acquire) &&
            context.deadline_exceeded()) {
          timed_out = true;
          result = scheduler_error("deadline_exceeded",
                                   "tool execution exceeded its deadline");
        }
      }
    }

    finish(std::move(control), have_result, timed_out, std::move(result));
  }

  void finish(std::shared_ptr<Control> control, const bool have_result,
              const bool timed_out, ToolExecutionResult result) {
    bool send_completion = false;
    {
      std::lock_guard lock{mutex};
      const auto entry = in_flight.find(control->key);
      if (entry != in_flight.end() && entry->second == control) {
        const bool cancelled =
            control->cancelled_by_client.load(std::memory_order_acquire);
        if (cancelled) {
          ++statistics.cancelled;
        } else if (timed_out) {
          ++statistics.timed_out;
          ++statistics.completed;
          send_completion = have_result;
        } else {
          ++statistics.completed;
          send_completion = have_result;
        }
        in_flight.erase(entry);
        statistics.outstanding = in_flight.size();
        statistics.queued = ready.size();
      }
    }
    done_cv.notify_all();

    if (send_completion) {
      try {
        completion(control->call.request_id, std::move(result));
      } catch (...) {
        // Protocol output failures are tracked by the completion sink. A worker
        // must never terminate the process by propagating callback exceptions.
      }
    }
  }

  ToolSubmitStatus submit(ScheduledToolCall call) {
    auto control = std::make_shared<Control>();
    control->key = request_key(call.request_id);
    control->call = std::move(call);
    control->deadline = OperationContext::Clock::now() +
                        std::chrono::milliseconds{budget.operation_timeout_ms};

    {
      std::lock_guard lock{mutex};
      if (!accepting) {
        return ToolSubmitStatus::kStopped;
      }
      if (in_flight.contains(control->key)) {
        ++statistics.duplicate_rejections;
        return ToolSubmitStatus::kDuplicateRequestId;
      }
      if (in_flight.size() >= budget.max_pending_requests) {
        ++statistics.queue_rejections;
        return ToolSubmitStatus::kQueueFull;
      }
      in_flight.emplace(control->key, control);
      ++statistics.accepted;
      statistics.outstanding = in_flight.size();
    }

    try {
      run(control);
    } catch (...) {
      {
        std::lock_guard lock{mutex};
        in_flight.erase(control->key);
        statistics.outstanding = in_flight.size();
      }
      done_cv.notify_all();
      return ToolSubmitStatus::kStopped;
    }
    return ToolSubmitStatus::kAccepted;
  }

  bool cancel(const Json& request_id) {
    std::shared_ptr<Control> control;
    {
      std::lock_guard lock{mutex};
      const auto entry = in_flight.find(request_key(request_id));
      if (entry == in_flight.end()) {
        return false;
      }
      control = entry->second;
      control->cancelled_by_client.store(true, std::memory_order_release);
    }
    (void)control->stop_source.request_stop();
    return true;
  }

  void shutdown() {
    std::lock_guard shutdown_lock{shutdown_mutex};
    {
      std::unique_lock lock{mutex};
      if (joined) {
        return;
      }
      accepting = false;
      done_cv.wait(lock, [this] { return in_flight.empty(); });
      stopping = true;
    }
    ready_cv.notify_all();
    bool skipped_current_worker = false;
    for (std::thread& worker : workers) {
      if (worker.joinable()) {
        if (worker.get_id() == std::this_thread::get_id()) {
          skipped_current_worker = true;
          continue;
        }
        worker.join();
      }
    }
    // A completion callback can request shutdown on a worker. It cannot join
    // itself; a later non-worker shutdown (including destruction) reaps it.
    joined = !skipped_current_worker;
  }

  ToolSchedulerStats stats() const {
    std::lock_guard lock{mutex};
    ToolSchedulerStats result = statistics;
    result.outstanding = in_flight.size();
    result.queued = ready.size();
    return result;
  }

  ResourceBudget budget;
  ToolExecutor executor;
  ToolCompletion completion;
  mutable std::mutex mutex;
  std::mutex shutdown_mutex;
  std::condition_variable ready_cv;
  std::condition_variable done_cv;
  std::vector<std::coroutine_handle<>> ready;
  std::unordered_map<std::string, std::shared_ptr<Control>> in_flight;
  std::vector<std::thread> workers;
  ToolSchedulerStats statistics;
  bool accepting = true;
  bool stopping = false;
  bool joined = false;
};

ToolScheduler::ToolScheduler(const ResourceBudget budget, ToolExecutor executor,
                             ToolCompletion completion)
    : ToolScheduler(budget, std::move(executor), std::move(completion),
                    default_worker_thread_factory) {}

ToolScheduler::ToolScheduler(const ResourceBudget budget, ToolExecutor executor,
                             ToolCompletion completion,
                             WorkerThreadFactory worker_factory)
    : impl_(std::make_unique<Impl>(budget, std::move(executor),
                                  std::move(completion),
                                  std::move(worker_factory))) {}

ToolScheduler::ToolScheduler(const ResourceBudget budget,
                             std::shared_ptr<ToolService> tools,
                             ToolCompletion completion)
    : ToolScheduler(
          budget,
          [tools = std::move(tools)](const std::string_view name,
                                     const Json& arguments,
                                     const OperationContext& context) {
            if (tools == nullptr) {
              return scheduler_error("internal_error",
                                     "tool service is unavailable");
            }
            return tools->execute(name, arguments, context);
          },
          std::move(completion)) {}

ToolScheduler::~ToolScheduler() = default;

ToolSubmitStatus ToolScheduler::submit(ScheduledToolCall call) {
  return impl_->submit(std::move(call));
}

bool ToolScheduler::cancel(const Json& request_id) {
  return impl_->cancel(request_id);
}

void ToolScheduler::shutdown() { impl_->shutdown(); }

ToolSchedulerStats ToolScheduler::stats() const { return impl_->stats(); }

}  // namespace native_mcp
