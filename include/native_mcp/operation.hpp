#pragma once

#include <chrono>
#include <stop_token>

namespace native_mcp {

enum class OperationStopReason {
  kNone,
  kCancelled,
  kDeadlineExceeded,
};

class OperationContext final {
 public:
  using Clock = std::chrono::steady_clock;

  OperationContext() noexcept = default;
  OperationContext(std::stop_token stop_token,
                   Clock::time_point deadline) noexcept
      : stop_token_(stop_token), deadline_(deadline) {}

  [[nodiscard]] bool cancellation_requested() const noexcept {
    return stop_token_.stop_requested();
  }

  [[nodiscard]] bool deadline_exceeded() const noexcept {
    return deadline_ != Clock::time_point::max() && Clock::now() >= deadline_;
  }

  [[nodiscard]] OperationStopReason stop_reason() const noexcept {
    if (cancellation_requested()) {
      return OperationStopReason::kCancelled;
    }
    if (deadline_exceeded()) {
      return OperationStopReason::kDeadlineExceeded;
    }
    return OperationStopReason::kNone;
  }

  [[nodiscard]] bool should_stop() const noexcept {
    return stop_reason() != OperationStopReason::kNone;
  }

  [[nodiscard]] Clock::time_point deadline() const noexcept {
    return deadline_;
  }

 private:
  std::stop_token stop_token_{};
  Clock::time_point deadline_{Clock::time_point::max()};
};

}  // namespace native_mcp
