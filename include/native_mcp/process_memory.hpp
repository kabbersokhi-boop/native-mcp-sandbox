#pragma once

#include "native_mcp/file_policy.hpp"
#include "native_mcp/operation.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace native_mcp {

enum class ProcessMemoryErrorCode {
  kInvalidConfig,
  kTooManyProcesses,
  kInvalidProcessName,
  kInvalidPid,
  kDuplicateProcess,
  kKernelUnsupported,
  kProcessMissing,
  kPermissionDenied,
  kDifferentUser,
  kProcessChanged,
  kProcUnavailable,
  kMalformedProcData,
  kDataTooLarge,
  kIoError,
  kUnknownProcess,
  kCancelled,
  kDeadlineExceeded,
};

struct ProcessMemoryError final {
  ProcessMemoryErrorCode code;
  std::string message;
};

struct ProcessTargetConfig final {
  std::string name;
  std::optional<std::uint32_t> pid;  // null means the server process itself
};

struct ProcessPolicyConfig final {
  std::vector<ProcessTargetConfig> processes;
};

struct ProcessPolicyLimits final {
  std::size_t max_processes = 16U;
  std::size_t max_name_bytes = 64U;
  std::size_t max_stat_bytes = 8U * 1024U;
  std::size_t max_status_bytes = 64U * 1024U;
  std::size_t max_statm_bytes = 4U * 1024U;
  std::size_t max_smaps_rollup_bytes = 256U * 1024U;
  bool allow_legacy_process_pinning = false;
};

struct ProcessStatusMemory final {
  std::optional<std::uint64_t> vm_peak_bytes;
  std::optional<std::uint64_t> vm_size_bytes;
  std::optional<std::uint64_t> vm_hwm_bytes;
  std::optional<std::uint64_t> vm_rss_bytes;
  std::optional<std::uint64_t> rss_anon_bytes;
  std::optional<std::uint64_t> rss_file_bytes;
  std::optional<std::uint64_t> rss_shmem_bytes;
  std::optional<std::uint64_t> vm_data_bytes;
  std::optional<std::uint64_t> vm_stack_bytes;
  std::optional<std::uint64_t> vm_executable_bytes;
  std::optional<std::uint64_t> vm_library_bytes;
  std::optional<std::uint64_t> vm_page_table_bytes;
  std::optional<std::uint64_t> vm_swap_bytes;
  std::optional<std::uint64_t> hugetlb_bytes;
};

struct ProcessStatmMemory final {
  std::uint64_t virtual_bytes = 0U;
  std::uint64_t resident_bytes = 0U;
  std::uint64_t shared_bytes = 0U;
  std::uint64_t text_bytes = 0U;
  std::uint64_t data_and_stack_bytes = 0U;
};

struct ProcessSmapsRollup final {
  std::optional<std::uint64_t> rss_bytes;
  std::optional<std::uint64_t> pss_bytes;
  std::optional<std::uint64_t> pss_anon_bytes;
  std::optional<std::uint64_t> pss_file_bytes;
  std::optional<std::uint64_t> pss_shmem_bytes;
  std::optional<std::uint64_t> shared_clean_bytes;
  std::optional<std::uint64_t> shared_dirty_bytes;
  std::optional<std::uint64_t> private_clean_bytes;
  std::optional<std::uint64_t> private_dirty_bytes;
  std::optional<std::uint64_t> referenced_bytes;
  std::optional<std::uint64_t> anonymous_bytes;
  std::optional<std::uint64_t> swap_bytes;
  std::optional<std::uint64_t> swap_pss_bytes;
  std::optional<std::uint64_t> locked_bytes;
};

struct ProcessMemoryResult final {
  std::string process;
  std::uint32_t pid = 0U;
  std::uint32_t uid = 0U;
  std::string name;
  std::string state;
  std::uint64_t threads = 0U;
  std::uint64_t page_size_bytes = 0U;
  bool pidfd_pinned = false;
  ProcessStatusMemory status;
  ProcessStatmMemory statm;
  bool smaps_rollup_available = false;
  std::optional<std::string> smaps_rollup_error;
  std::optional<ProcessSmapsRollup> smaps_rollup;
};

struct ProcessMemoryOutcome final {
  std::optional<ProcessMemoryResult> result;
  std::optional<ProcessMemoryError> error;
};

class ProcessPolicy final {
 public:
  ProcessPolicy() = default;
  ~ProcessPolicy() = default;

  ProcessPolicy(const ProcessPolicy&) = delete;
  ProcessPolicy& operator=(const ProcessPolicy&) = delete;
  ProcessPolicy(ProcessPolicy&&) noexcept = default;
  ProcessPolicy& operator=(ProcessPolicy&&) noexcept = default;

  struct CreateResult;

  [[nodiscard]] static CreateResult create(
      const ProcessPolicyConfig& config, ProcessPolicyLimits limits = {});

  [[nodiscard]] ProcessMemoryOutcome inspect_memory(
      std::string_view process_name, OperationContext context = {}) const;
  [[nodiscard]] std::size_t process_count() const noexcept;
  [[nodiscard]] bool uses_legacy_pinning() const noexcept;

 private:
  struct ProcessHandle final {
    std::string name;
    std::uint32_t pid;
    std::uint32_t uid;
    std::uint64_t start_time_ticks;
    UniqueFd proc_directory;
    UniqueFd pidfd;
  };

  explicit ProcessPolicy(ProcessPolicyLimits limits) noexcept;

  ProcessPolicyLimits limits_{};
  std::vector<ProcessHandle> processes_;
  bool uses_legacy_pinning_ = false;
};

struct ProcessPolicy::CreateResult final {
  std::optional<ProcessPolicy> policy;
  std::optional<ProcessMemoryError> error;
};

[[nodiscard]] std::string_view process_memory_error_name(
    ProcessMemoryErrorCode code) noexcept;

}  // namespace native_mcp
