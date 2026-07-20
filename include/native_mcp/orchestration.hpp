#pragma once

#include "native_mcp/foundation.hpp"
#include "native_mcp/operation.hpp"
#include "native_mcp/tool_service.hpp"

#include <nlohmann/json.hpp>

#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <thread>

namespace native_mcp {

enum class ToolSubmitStatus {
  kAccepted,
  kQueueFull,
  kDuplicateRequestId,
  kStopped,
};

struct ScheduledToolCall final {
  nlohmann::json request_id;
  std::string name;
  nlohmann::json arguments;
};

struct ToolSchedulerStats final {
  std::size_t accepted = 0U;
  std::size_t completed = 0U;
  std::size_t cancelled = 0U;
  std::size_t timed_out = 0U;
  std::size_t queue_rejections = 0U;
  std::size_t duplicate_rejections = 0U;
  std::size_t outstanding = 0U;
  std::size_t queued = 0U;
};

using ToolExecutor = std::function<ToolExecutionResult(
    std::string_view, const nlohmann::json&, const OperationContext&)>;
using ToolCompletion = std::function<void(
    const nlohmann::json&, ToolExecutionResult)>;
using WorkerThreadFactory =
    std::function<std::thread(std::function<void()>)>;

class ToolScheduler final {
 public:
  ToolScheduler(ResourceBudget budget, ToolExecutor executor,
                ToolCompletion completion);
  ToolScheduler(ResourceBudget budget, ToolExecutor executor,
                ToolCompletion completion, WorkerThreadFactory worker_factory);
  ToolScheduler(ResourceBudget budget, std::shared_ptr<ToolService> tools,
                ToolCompletion completion);
  ~ToolScheduler();

  ToolScheduler(const ToolScheduler&) = delete;
  ToolScheduler& operator=(const ToolScheduler&) = delete;
  ToolScheduler(ToolScheduler&&) = delete;
  ToolScheduler& operator=(ToolScheduler&&) = delete;

  [[nodiscard]] ToolSubmitStatus submit(ScheduledToolCall call);
  [[nodiscard]] bool cancel(const nlohmann::json& request_id);
  // A completion callback may call shutdown(). It must not destroy this
  // scheduler from that callback; destruction is supported only after a
  // non-worker caller has completed the deferred join.
  void shutdown();
  [[nodiscard]] ToolSchedulerStats stats() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace native_mcp
