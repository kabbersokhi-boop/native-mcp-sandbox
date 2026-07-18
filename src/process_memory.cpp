#include "native_mcp/process_memory.hpp"

#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <cctype>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

namespace native_mcp {
namespace {

[[nodiscard]] ProcessMemoryError error(const ProcessMemoryErrorCode code,
                                       std::string message) {
  return ProcessMemoryError{.code = code, .message = std::move(message)};
}

[[nodiscard]] std::optional<ProcessMemoryError> operation_error(
    const OperationContext& context) {
  switch (context.stop_reason()) {
    case OperationStopReason::kCancelled:
      return error(ProcessMemoryErrorCode::kCancelled,
                   "process observation was cancelled");
    case OperationStopReason::kDeadlineExceeded:
      return error(ProcessMemoryErrorCode::kDeadlineExceeded,
                   "process observation exceeded its deadline");
    case OperationStopReason::kNone:
      return std::nullopt;
  }
  return std::nullopt;
}

[[nodiscard]] bool valid_process_name(const std::string_view name,
                                      const std::size_t maximum) {
  if (name.empty() || name.size() > maximum) {
    return false;
  }
  for (const char raw : name) {
    const auto value = static_cast<unsigned char>(raw);
    if (!(std::isalnum(value) != 0 || value == '-' || value == '_')) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] std::optional<std::uint64_t> parse_unsigned(
    const std::string_view text) {
  if (text.empty()) {
    return std::nullopt;
  }
  std::uint64_t value = 0U;
  const char* const first = text.data();
  const char* const last = text.data() + text.size();
  const auto parsed = std::from_chars(first, last, value);
  if (parsed.ec != std::errc{} || parsed.ptr != last) {
    return std::nullopt;
  }
  return value;
}

[[nodiscard]] bool checked_multiply(const std::uint64_t left,
                                    const std::uint64_t right,
                                    std::uint64_t& result) noexcept {
  if (left != 0U && right > std::numeric_limits<std::uint64_t>::max() / left) {
    return false;
  }
  result = left * right;
  return true;
}

[[nodiscard]] ProcessMemoryError map_proc_open_error(const int number,
                                                     const std::string_view file) {
  switch (number) {
    case ENOENT:
    case ESRCH:
      return error(ProcessMemoryErrorCode::kProcessMissing,
                   "configured process is no longer available");
    case EACCES:
    case EPERM:
      return error(ProcessMemoryErrorCode::kPermissionDenied,
                   std::string{"permission denied reading /proc process "} +
                       std::string{file});
    default:
      return error(ProcessMemoryErrorCode::kIoError,
                   std::string{"failed to open /proc process "} +
                       std::string{file} + ": " + std::strerror(number));
  }
}

struct ReadTextResult final {
  std::optional<std::string> text;
  std::optional<ProcessMemoryError> error;
};

[[nodiscard]] ReadTextResult read_proc_text(
    const int directory_fd, const char* name, const std::size_t limit,
    const bool optional_file, const OperationContext context = {}) {
  if (const auto stopped = operation_error(context)) {
    return {.text = std::nullopt, .error = stopped};
  }
  UniqueFd descriptor{
      ::openat(directory_fd, name,
               O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)};
  if (!descriptor.valid()) {
    if (optional_file && errno == ENOENT) {
      return {.text = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kProcUnavailable,
                             std::string{"optional /proc process "} + name +
                                 " is unavailable")};
    }
    return {.text = std::nullopt, .error = map_proc_open_error(errno, name)};
  }

  std::string output(limit + 1U, '\0');
  std::size_t total = 0U;
  while (total < output.size()) {
    if (const auto stopped = operation_error(context)) {
      return {.text = std::nullopt, .error = stopped};
    }
    const ssize_t count = ::read(descriptor.get(), output.data() + total,
                                 output.size() - total);
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return {.text = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kIoError,
                             std::string{"failed while reading /proc process "} +
                                 name)};
    }
    if (count == 0) {
      break;
    }
    total += static_cast<std::size_t>(count);
  }
  if (total > limit) {
    return {.text = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kDataTooLarge,
                           std::string{"/proc process "} + name +
                               " exceeds the bounded read limit")};
  }
  output.resize(total);
  return {.text = std::move(output), .error = std::nullopt};
}

struct StatIdentity final {
  std::string name;
  std::string state;
  std::uint64_t start_time_ticks = 0U;
};

[[nodiscard]] std::optional<StatIdentity> parse_stat_identity(
    const std::string_view text) {
  const std::size_t open = text.find('(');
  const std::size_t close = text.rfind(')');
  if (open == std::string_view::npos || close == std::string_view::npos ||
      close <= open || close + 2U >= text.size()) {
    return std::nullopt;
  }
  StatIdentity identity;
  identity.name = std::string{text.substr(open + 1U, close - open - 1U)};
  std::string_view remainder = text.substr(close + 2U);
  std::array<std::string_view, 20U> fields{};
  std::size_t count = 0U;
  std::size_t start = 0U;
  while (start < remainder.size() && count < fields.size()) {
    while (start < remainder.size() && remainder[start] == ' ') {
      ++start;
    }
    if (start >= remainder.size()) {
      break;
    }
    const std::size_t end = remainder.find(' ', start);
    fields[count] = remainder.substr(
        start, end == std::string_view::npos ? remainder.size() - start
                                            : end - start);
    ++count;
    if (end == std::string_view::npos) {
      break;
    }
    start = end + 1U;
  }
  if (count < 20U || fields[0].size() != 1U) {
    return std::nullopt;
  }
  const auto start_time = parse_unsigned(fields[19]);
  if (!start_time.has_value()) {
    return std::nullopt;
  }
  identity.state = std::string{fields[0]};
  identity.start_time_ticks = *start_time;
  return identity;
}

[[nodiscard]] std::optional<std::string_view> value_after_colon(
    const std::string_view line, const std::string_view key) {
  if (!line.starts_with(key) || line.size() <= key.size() ||
      line[key.size()] != ':') {
    return std::nullopt;
  }
  std::string_view value = line.substr(key.size() + 1U);
  while (!value.empty() && (value.front() == ' ' || value.front() == '\t')) {
    value.remove_prefix(1U);
  }
  while (!value.empty() &&
         (value.back() == ' ' || value.back() == '\t' || value.back() == '\r')) {
    value.remove_suffix(1U);
  }
  return value;
}

[[nodiscard]] std::optional<std::uint64_t> parse_kibibytes(
    std::string_view value) {
  const std::size_t space = value.find_first_of(" \t");
  const std::string_view number = value.substr(0U, space);
  const auto parsed = parse_unsigned(number);
  if (!parsed.has_value()) {
    return std::nullopt;
  }
  if (space != std::string_view::npos) {
    value.remove_prefix(space);
    while (!value.empty() && (value.front() == ' ' || value.front() == '\t')) {
      value.remove_prefix(1U);
    }
    if (value != "kB") {
      return std::nullopt;
    }
  }
  std::uint64_t bytes = 0U;
  if (!checked_multiply(*parsed, 1024U, bytes)) {
    return std::nullopt;
  }
  return bytes;
}

struct StatusParseResult final {
  std::string name;
  std::string state;
  std::uint32_t effective_uid = 0U;
  std::uint64_t threads = 0U;
  ProcessStatusMemory memory;
};

void assign_status_metric(const std::string_view key,
                          const std::optional<std::uint64_t> value,
                          ProcessStatusMemory& memory) {
  if (key == "VmPeak") {
    memory.vm_peak_bytes = value;
  } else if (key == "VmSize") {
    memory.vm_size_bytes = value;
  } else if (key == "VmHWM") {
    memory.vm_hwm_bytes = value;
  } else if (key == "VmRSS") {
    memory.vm_rss_bytes = value;
  } else if (key == "RssAnon") {
    memory.rss_anon_bytes = value;
  } else if (key == "RssFile") {
    memory.rss_file_bytes = value;
  } else if (key == "RssShmem") {
    memory.rss_shmem_bytes = value;
  } else if (key == "VmData") {
    memory.vm_data_bytes = value;
  } else if (key == "VmStk") {
    memory.vm_stack_bytes = value;
  } else if (key == "VmExe") {
    memory.vm_executable_bytes = value;
  } else if (key == "VmLib") {
    memory.vm_library_bytes = value;
  } else if (key == "VmPTE") {
    memory.vm_page_table_bytes = value;
  } else if (key == "VmSwap") {
    memory.vm_swap_bytes = value;
  } else if (key == "HugetlbPages") {
    memory.hugetlb_bytes = value;
  }
}

[[nodiscard]] std::optional<StatusParseResult> parse_status(
    const std::string_view text) {
  StatusParseResult result;
  bool have_name = false;
  bool have_state = false;
  bool have_uid = false;
  bool have_threads = false;
  std::size_t start = 0U;
  while (start <= text.size()) {
    const std::size_t newline = text.find('\n', start);
    const std::size_t end = newline == std::string_view::npos ? text.size() : newline;
    const std::string_view line = text.substr(start, end - start);
    if (const auto value = value_after_colon(line, "Name")) {
      result.name = std::string{*value};
      have_name = true;
    } else if (const auto value = value_after_colon(line, "State")) {
      result.state = std::string{*value};
      have_state = true;
    } else if (const auto value = value_after_colon(line, "Threads")) {
      const auto parsed = parse_unsigned(*value);
      if (!parsed.has_value()) {
        return std::nullopt;
      }
      result.threads = *parsed;
      have_threads = true;
    } else if (const auto value = value_after_colon(line, "Uid")) {
      std::array<std::string_view, 4U> ids{};
      std::size_t id_count = 0U;
      std::size_t position = 0U;
      while (position < value->size() && id_count < ids.size()) {
        while (position < value->size() &&
               ((*value)[position] == ' ' || (*value)[position] == '\t')) {
          ++position;
        }
        if (position >= value->size()) {
          break;
        }
        const std::size_t separator = value->find_first_of(" \t", position);
        ids[id_count] = value->substr(
            position, separator == std::string_view::npos
                          ? value->size() - position
                          : separator - position);
        ++id_count;
        if (separator == std::string_view::npos) {
          break;
        }
        position = separator + 1U;
      }
      if (id_count < 2U) {
        return std::nullopt;
      }
      const auto uid = parse_unsigned(ids[1]);
      if (!uid.has_value() || *uid > std::numeric_limits<std::uint32_t>::max()) {
        return std::nullopt;
      }
      result.effective_uid = static_cast<std::uint32_t>(*uid);
      have_uid = true;
    } else {
      static constexpr std::array<std::string_view, 14U> kMemoryKeys{
          "VmPeak", "VmSize", "VmHWM", "VmRSS", "RssAnon", "RssFile",
          "RssShmem", "VmData", "VmStk", "VmExe", "VmLib", "VmPTE",
          "VmSwap", "HugetlbPages"};
      for (const std::string_view key : kMemoryKeys) {
        if (const auto value = value_after_colon(line, key)) {
          const auto parsed = parse_kibibytes(*value);
          if (!parsed.has_value()) {
            return std::nullopt;
          }
          assign_status_metric(key, parsed, result.memory);
          break;
        }
      }
    }
    if (newline == std::string_view::npos) {
      break;
    }
    start = newline + 1U;
  }
  if (!have_name || !have_state || !have_uid || !have_threads) {
    return std::nullopt;
  }
  return result;
}

[[nodiscard]] std::optional<ProcessStatmMemory> parse_statm(
    const std::string_view text, const std::uint64_t page_size) {
  std::array<std::uint64_t, 7U> pages{};
  std::size_t count = 0U;
  std::size_t position = 0U;
  while (position < text.size() && count < pages.size()) {
    while (position < text.size() &&
           (text[position] == ' ' || text[position] == '\t' ||
            text[position] == '\n' || text[position] == '\r')) {
      ++position;
    }
    if (position >= text.size()) {
      break;
    }
    const std::size_t end = text.find_first_of(" \t\r\n", position);
    const std::string_view token = text.substr(
        position, end == std::string_view::npos ? text.size() - position
                                                : end - position);
    const auto value = parse_unsigned(token);
    if (!value.has_value()) {
      return std::nullopt;
    }
    pages[count] = *value;
    ++count;
    if (end == std::string_view::npos) {
      break;
    }
    position = end + 1U;
  }
  if (count < 7U) {
    return std::nullopt;
  }
  ProcessStatmMemory result;
  if (!checked_multiply(pages[0], page_size, result.virtual_bytes) ||
      !checked_multiply(pages[1], page_size, result.resident_bytes) ||
      !checked_multiply(pages[2], page_size, result.shared_bytes) ||
      !checked_multiply(pages[3], page_size, result.text_bytes) ||
      !checked_multiply(pages[5], page_size, result.data_and_stack_bytes)) {
    return std::nullopt;
  }
  return result;
}

void assign_rollup_metric(const std::string_view key,
                          const std::optional<std::uint64_t> value,
                          ProcessSmapsRollup& rollup) {
  if (key == "Rss") {
    rollup.rss_bytes = value;
  } else if (key == "Pss") {
    rollup.pss_bytes = value;
  } else if (key == "Pss_Anon") {
    rollup.pss_anon_bytes = value;
  } else if (key == "Pss_File") {
    rollup.pss_file_bytes = value;
  } else if (key == "Pss_Shmem") {
    rollup.pss_shmem_bytes = value;
  } else if (key == "Shared_Clean") {
    rollup.shared_clean_bytes = value;
  } else if (key == "Shared_Dirty") {
    rollup.shared_dirty_bytes = value;
  } else if (key == "Private_Clean") {
    rollup.private_clean_bytes = value;
  } else if (key == "Private_Dirty") {
    rollup.private_dirty_bytes = value;
  } else if (key == "Referenced") {
    rollup.referenced_bytes = value;
  } else if (key == "Anonymous") {
    rollup.anonymous_bytes = value;
  } else if (key == "Swap") {
    rollup.swap_bytes = value;
  } else if (key == "SwapPss") {
    rollup.swap_pss_bytes = value;
  } else if (key == "Locked") {
    rollup.locked_bytes = value;
  }
}

[[nodiscard]] std::optional<ProcessSmapsRollup> parse_smaps_rollup(
    const std::string_view text) {
  ProcessSmapsRollup result;
  bool recognized = false;
  static constexpr std::array<std::string_view, 14U> kKeys{
      "Rss",          "Pss",           "Pss_Anon",      "Pss_File",
      "Pss_Shmem",    "Shared_Clean",  "Shared_Dirty",  "Private_Clean",
      "Private_Dirty", "Referenced",   "Anonymous",     "Swap",
      "SwapPss",      "Locked"};
  std::size_t start = 0U;
  while (start <= text.size()) {
    const std::size_t newline = text.find('\n', start);
    const std::size_t end = newline == std::string_view::npos ? text.size() : newline;
    const std::string_view line = text.substr(start, end - start);
    for (const std::string_view key : kKeys) {
      if (const auto value = value_after_colon(line, key)) {
        const auto parsed = parse_kibibytes(*value);
        if (!parsed.has_value()) {
          return std::nullopt;
        }
        assign_rollup_metric(key, parsed, result);
        recognized = true;
        break;
      }
    }
    if (newline == std::string_view::npos) {
      break;
    }
    start = newline + 1U;
  }
  if (!recognized) {
    return std::nullopt;
  }
  return result;
}

[[nodiscard]] bool pidfd_has_exited(const int pidfd) {
  pollfd descriptor{.fd = pidfd, .events = POLLIN, .revents = 0};
  int result = -1;
  do {
    result = ::poll(&descriptor, 1U, 0);
  } while (result < 0 && errno == EINTR);
  if (result < 0) {
    return true;
  }
  return result > 0 &&
         (descriptor.revents & static_cast<short>(POLLIN | POLLHUP)) != 0;
}

[[nodiscard]] int open_pidfd(const std::uint32_t pid) {
#ifdef SYS_pidfd_open
  return static_cast<int>(
      ::syscall(SYS_pidfd_open, static_cast<pid_t>(pid), 0U));
#else
  (void)pid;
  errno = ENOSYS;
  return -1;
#endif
}

[[nodiscard]] std::optional<StatIdentity> read_identity(
    const int proc_directory, const ProcessPolicyLimits& limits,
    ProcessMemoryError& failure, const OperationContext context = {}) {
  ReadTextResult stat = read_proc_text(proc_directory, "stat",
                                       limits.max_stat_bytes, false, context);
  if (!stat.text.has_value()) {
    failure = std::move(*stat.error);
    return std::nullopt;
  }
  const auto parsed = parse_stat_identity(*stat.text);
  if (!parsed.has_value()) {
    failure = error(ProcessMemoryErrorCode::kMalformedProcData,
                    "could not parse bounded /proc process stat data");
    return std::nullopt;
  }
  return parsed;
}

}  // namespace

ProcessPolicy::ProcessPolicy(const ProcessPolicyLimits limits) noexcept
    : limits_(limits) {}

ProcessPolicy::CreateResult ProcessPolicy::create(
    const ProcessPolicyConfig& config, const ProcessPolicyLimits limits) {
  if (config.processes.empty() || config.processes.size() > limits.max_processes) {
    return {.policy = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kTooManyProcesses,
                           "configuration must contain between one and the process limit")};
  }
  ProcessPolicy policy{limits};
  std::unordered_set<std::string> names;
  UniqueFd proc_root{::open("/proc", O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW)};
  if (!proc_root.valid()) {
    return {.policy = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kProcUnavailable,
                           "could not open the proc filesystem")};
  }

  for (const ProcessTargetConfig& target : config.processes) {
    if (!valid_process_name(target.name, limits.max_name_bytes)) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kInvalidProcessName,
                             "process name contains unsupported characters")};
    }
    if (!names.insert(target.name).second) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kDuplicateProcess,
                             "process names must be unique")};
    }
    const std::uint64_t resolved = target.pid.has_value()
                                       ? static_cast<std::uint64_t>(*target.pid)
                                       : static_cast<std::uint64_t>(::getpid());
    if (resolved == 0U || resolved > static_cast<std::uint64_t>(INT_MAX)) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kInvalidPid,
                             "configured process PID is outside the accepted range")};
    }
    const auto pid = static_cast<std::uint32_t>(resolved);
    UniqueFd pidfd{open_pidfd(pid)};
    if (!pidfd.valid()) {
      const int number = errno;
      const bool unsupported = number == ENOSYS || number == EINVAL;
      if (!unsupported || !limits.allow_legacy_process_pinning) {
        if (unsupported) {
          return {.policy = std::nullopt,
                  .error = error(ProcessMemoryErrorCode::kKernelUnsupported,
                                 "pidfd process pinning is unavailable")};
        }
        return {.policy = std::nullopt,
                .error = map_proc_open_error(number, "pidfd")};
      }
      policy.uses_legacy_pinning_ = true;
    } else if (pidfd_has_exited(pidfd.get())) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kProcessMissing,
                             "configured process exited during startup")};
    }

    const std::string component = std::to_string(pid);
    UniqueFd directory{
        ::openat(proc_root.get(), component.c_str(),
                 O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW)};
    if (!directory.valid()) {
      return {.policy = std::nullopt,
              .error = map_proc_open_error(errno, "directory")};
    }

    ReadTextResult status =
        read_proc_text(directory.get(), "status", limits.max_status_bytes, false);
    if (!status.text.has_value()) {
      return {.policy = std::nullopt, .error = std::move(status.error)};
    }
    const auto parsed_status = parse_status(*status.text);
    if (!parsed_status.has_value()) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kMalformedProcData,
                             "could not parse bounded /proc process status data")};
    }
    const auto server_uid = static_cast<std::uint32_t>(::geteuid());
    if (parsed_status->effective_uid != server_uid) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kDifferentUser,
                             "configured process does not share the server effective UID")};
    }
    ProcessMemoryError identity_error =
        error(ProcessMemoryErrorCode::kMalformedProcData, "invalid process identity");
    const auto identity = read_identity(directory.get(), limits, identity_error);
    if (!identity.has_value()) {
      return {.policy = std::nullopt, .error = std::move(identity_error)};
    }

    if (pidfd.valid() && pidfd_has_exited(pidfd.get())) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kProcessMissing,
                             "configured process exited while procfs identity was opened")};
    }
    const auto confirmed_identity =
        read_identity(directory.get(), limits, identity_error);
    if (!confirmed_identity.has_value() ||
        confirmed_identity->start_time_ticks != identity->start_time_ticks) {
      return {.policy = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kProcessChanged,
                             "configured process changed while it was being pinned")};
    }

    policy.processes_.push_back(ProcessHandle{
        .name = target.name,
        .pid = pid,
        .uid = parsed_status->effective_uid,
        .start_time_ticks = identity->start_time_ticks,
        .proc_directory = std::move(directory),
        .pidfd = std::move(pidfd),
    });
  }

  return {.policy = std::move(policy), .error = std::nullopt};
}

ProcessMemoryOutcome ProcessPolicy::inspect_memory(
    const std::string_view process_name,
    const OperationContext context) const {
  if (const auto stopped = operation_error(context)) {
    return {.result = std::nullopt, .error = stopped};
  }
  const ProcessHandle* target = nullptr;
  for (const ProcessHandle& candidate : processes_) {
    if (candidate.name == process_name) {
      target = &candidate;
      break;
    }
  }
  if (target == nullptr) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kUnknownProcess,
                           "requested process is not configured")};
  }
  if (target->pidfd.valid() && pidfd_has_exited(target->pidfd.get())) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kProcessMissing,
                           "configured process has exited")};
  }

  ProcessMemoryError identity_error =
      error(ProcessMemoryErrorCode::kMalformedProcData, "invalid process identity");
  const auto before = read_identity(target->proc_directory.get(), limits_, identity_error, context);
  if (!before.has_value()) {
    return {.result = std::nullopt, .error = std::move(identity_error)};
  }
  if (before->start_time_ticks != target->start_time_ticks) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kProcessChanged,
                           "configured process identity no longer matches startup")};
  }

  ReadTextResult status_text = read_proc_text(
      target->proc_directory.get(), "status", limits_.max_status_bytes, false,
      context);
  if (!status_text.text.has_value()) {
    return {.result = std::nullopt, .error = std::move(status_text.error)};
  }
  const auto status = parse_status(*status_text.text);
  if (!status.has_value()) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kMalformedProcData,
                           "could not parse bounded /proc process status data")};
  }
  if (status->effective_uid != target->uid ||
      status->effective_uid != static_cast<std::uint32_t>(::geteuid())) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kDifferentUser,
                           "configured process credentials changed")};
  }

  const long page_size_raw = ::sysconf(_SC_PAGESIZE);
  if (page_size_raw <= 0) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kIoError,
                           "could not determine the system page size")};
  }
  const auto page_size = static_cast<std::uint64_t>(page_size_raw);
  ReadTextResult statm_text = read_proc_text(
      target->proc_directory.get(), "statm", limits_.max_statm_bytes, false,
      context);
  if (!statm_text.text.has_value()) {
    return {.result = std::nullopt, .error = std::move(statm_text.error)};
  }
  const auto statm = parse_statm(*statm_text.text, page_size);
  if (!statm.has_value()) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kMalformedProcData,
                           "could not parse bounded /proc process statm data")};
  }

  bool rollup_available = false;
  std::optional<std::string> rollup_error;
  std::optional<ProcessSmapsRollup> rollup;
  ReadTextResult rollup_text = read_proc_text(
      target->proc_directory.get(), "smaps_rollup",
      limits_.max_smaps_rollup_bytes, true, context);
  if (rollup_text.text.has_value()) {
    rollup = parse_smaps_rollup(*rollup_text.text);
    if (!rollup.has_value()) {
      return {.result = std::nullopt,
              .error = error(ProcessMemoryErrorCode::kMalformedProcData,
                             "could not parse bounded smaps_rollup data")};
    }
    rollup_available = true;
  } else if (rollup_text.error.has_value()) {
    rollup_error = std::string{process_memory_error_name(rollup_text.error->code)};
  }

  const auto after = read_identity(target->proc_directory.get(), limits_, identity_error, context);
  if (!after.has_value()) {
    return {.result = std::nullopt, .error = std::move(identity_error)};
  }
  if (after->start_time_ticks != target->start_time_ticks ||
      after->name != before->name) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kProcessChanged,
                           "configured process changed during observation")};
  }
  if (target->pidfd.valid() && pidfd_has_exited(target->pidfd.get())) {
    return {.result = std::nullopt,
            .error = error(ProcessMemoryErrorCode::kProcessMissing,
                           "configured process exited during observation")};
  }

  return {.result = ProcessMemoryResult{
              .process = target->name,
              .pid = target->pid,
              .uid = target->uid,
              .name = status->name,
              .state = status->state,
              .threads = status->threads,
              .page_size_bytes = page_size,
              .pidfd_pinned = target->pidfd.valid(),
              .status = status->memory,
              .statm = *statm,
              .smaps_rollup_available = rollup_available,
              .smaps_rollup_error = std::move(rollup_error),
              .smaps_rollup = std::move(rollup),
          },
          .error = std::nullopt};
}

std::size_t ProcessPolicy::process_count() const noexcept {
  return processes_.size();
}

bool ProcessPolicy::uses_legacy_pinning() const noexcept {
  return uses_legacy_pinning_;
}

std::string_view process_memory_error_name(
    const ProcessMemoryErrorCode code) noexcept {
  switch (code) {
    case ProcessMemoryErrorCode::kInvalidConfig:
      return "invalid_config";
    case ProcessMemoryErrorCode::kTooManyProcesses:
      return "process_count_invalid";
    case ProcessMemoryErrorCode::kInvalidProcessName:
      return "invalid_process_name";
    case ProcessMemoryErrorCode::kInvalidPid:
      return "invalid_pid";
    case ProcessMemoryErrorCode::kDuplicateProcess:
      return "duplicate_process";
    case ProcessMemoryErrorCode::kKernelUnsupported:
      return "kernel_unsupported";
    case ProcessMemoryErrorCode::kProcessMissing:
      return "process_missing";
    case ProcessMemoryErrorCode::kPermissionDenied:
      return "permission_denied";
    case ProcessMemoryErrorCode::kDifferentUser:
      return "different_user";
    case ProcessMemoryErrorCode::kProcessChanged:
      return "process_changed";
    case ProcessMemoryErrorCode::kProcUnavailable:
      return "proc_unavailable";
    case ProcessMemoryErrorCode::kMalformedProcData:
      return "malformed_proc_data";
    case ProcessMemoryErrorCode::kDataTooLarge:
      return "proc_data_too_large";
    case ProcessMemoryErrorCode::kIoError:
      return "io_error";
    case ProcessMemoryErrorCode::kUnknownProcess:
      return "unknown_process";
    case ProcessMemoryErrorCode::kCancelled:
      return "cancelled";
    case ProcessMemoryErrorCode::kDeadlineExceeded:
      return "deadline_exceeded";
  }
  return "unknown";
}

}  // namespace native_mcp
