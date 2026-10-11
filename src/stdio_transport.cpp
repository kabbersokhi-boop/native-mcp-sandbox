#include "native_mcp/stdio_transport.hpp"

#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <istream>
#include <ostream>
#include <streambuf>
#include <utility>

#include "native_mcp/server.hpp"

namespace native_mcp {
namespace {

using Clock = std::chrono::steady_clock;

class DescriptorMode final {
 public:
  explicit DescriptorMode(const int descriptor)
      : descriptor_(descriptor), flags_(::fcntl(descriptor, F_GETFL)) {
    valid_ = flags_ >= 0 && ::fcntl(descriptor_, F_SETFL, flags_ | O_NONBLOCK) == 0;
  }

  ~DescriptorMode() {
    if (valid_) {
      (void)::fcntl(descriptor_, F_SETFL, flags_);
    }
  }

  DescriptorMode(const DescriptorMode&) = delete;
  DescriptorMode& operator=(const DescriptorMode&) = delete;

  [[nodiscard]] bool valid() const noexcept { return valid_; }

 private:
  int descriptor_;
  int flags_;
  bool valid_ = false;
};

class PipeSignal final {
 public:
  PipeSignal() {
    struct sigaction ignored{};
    ignored.sa_handler = SIG_IGN;
    (void)::sigemptyset(&ignored.sa_mask);
    valid_ = ::sigaction(SIGPIPE, &ignored, &previous_) == 0;
  }

  ~PipeSignal() {
    if (valid_) {
      (void)::sigaction(SIGPIPE, &previous_, nullptr);
    }
  }

  PipeSignal(const PipeSignal&) = delete;
  PipeSignal& operator=(const PipeSignal&) = delete;

  [[nodiscard]] bool valid() const noexcept { return valid_; }

 private:
  struct sigaction previous_{};
  bool valid_ = false;
};

class DescriptorBuffer final : public std::streambuf {
 public:
  DescriptorBuffer(const int descriptor, std::atomic<bool>& failed,
                   const std::chrono::milliseconds write_timeout)
      : descriptor_(descriptor), failed_(failed), write_timeout_(write_timeout) {}

 protected:
  int_type underflow() override {
    if (gptr() != nullptr && gptr() < egptr()) {
      return traits_type::to_int_type(*gptr());
    }
    while (!failed_.load(std::memory_order_acquire)) {
      pollfd descriptor{descriptor_, POLLIN, 0};
      const int ready = ::poll(&descriptor, 1, 50);
      if (ready < 0) {
        if (errno == EINTR) {
          continue;
        }
        break;
      }
      if (ready == 0) {
        continue;
      }
      const ssize_t count = ::read(descriptor_, input_.data(), input_.size());
      if (count == 0) {
        return traits_type::eof();
      }
      if (count > 0) {
        setg(input_.data(), input_.data(), input_.data() + count);
        return traits_type::to_int_type(*gptr());
      }
      if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
        break;
      }
    }
    failed_.store(true, std::memory_order_release);
    return traits_type::eof();
  }

  std::streamsize xsputn(const char* data, const std::streamsize size) override {
    if (size <= 0) {
      return 0;
    }
    const auto deadline = Clock::now() + write_timeout_;
    std::streamsize written = 0;
    while (written < size && !failed_.load(std::memory_order_acquire)) {
      const auto now = Clock::now();
      if (now >= deadline) {
        break;
      }
      const ssize_t count =
          ::write(descriptor_, data + written, static_cast<std::size_t>(size - written));
      if (count > 0) {
        written += count;
        continue;
      }
      if (count < 0 && errno == EINTR) {
        continue;
      }
      if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        const auto remaining = std::chrono::ceil<std::chrono::milliseconds>(deadline - now);
        const int wait_ms = static_cast<int>(std::min(remaining.count(), std::int64_t{50}));
        pollfd descriptor{descriptor_, POLLOUT, 0};
        if (::poll(&descriptor, 1, wait_ms) >= 0 || errno == EINTR) {
          continue;
        }
      }
      break;
    }
    if (written != size) {
      failed_.store(true, std::memory_order_release);
    }
    return written;
  }

  int_type overflow(const int_type character) override {
    if (traits_type::eq_int_type(character, traits_type::eof())) {
      return traits_type::not_eof(character);
    }
    const char value = traits_type::to_char_type(character);
    return xsputn(&value, 1) == 1 ? character : traits_type::eof();
  }

  int sync() override { return failed_.load(std::memory_order_acquire) ? -1 : 0; }

 private:
  int descriptor_;
  std::atomic<bool>& failed_;
  std::chrono::milliseconds write_timeout_;
  std::array<char, 4096> input_{};
};

}  // namespace

int run_native_stdio(const ResourceBudget budget, std::optional<ToolService> tools,
                     const std::chrono::milliseconds write_timeout) {
  if (write_timeout <= std::chrono::milliseconds::zero() ||
      write_timeout > std::chrono::seconds{30}) {
    return 78;
  }
  PipeSignal pipe_signal;
  DescriptorMode input_mode{STDIN_FILENO};
  DescriptorMode output_mode{STDOUT_FILENO};
  DescriptorMode diagnostic_mode{STDERR_FILENO};
  if (!pipe_signal.valid() || !input_mode.valid() || !output_mode.valid() ||
      !diagnostic_mode.valid()) {
    return 74;
  }
  std::atomic<bool> failed{false};
  DescriptorBuffer input_buffer{STDIN_FILENO, failed, write_timeout};
  DescriptorBuffer output_buffer{STDOUT_FILENO, failed, write_timeout};
  DescriptorBuffer diagnostic_buffer{STDERR_FILENO, failed, write_timeout};
  std::istream input{&input_buffer};
  std::ostream output{&output_buffer};
  std::ostream diagnostics{&diagnostic_buffer};
  const int status = run_stdio(input, output, diagnostics, budget, std::move(tools),
                               [&failed] { return failed.load(std::memory_order_acquire); });
  return failed.load(std::memory_order_acquire) ? 74 : status;
}

}  // namespace native_mcp
