#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace native_mcp {

enum class PolicyErrorCode {
  kInvalidConfig,
  kConfigTooLarge,
  kTooManyRoots,
  kInvalidRootName,
  kInvalidRootPath,
  kDuplicateRoot,
  kOpenRootFailed,
  kKernelUnsupported,
  kUnknownRoot,
  kInvalidRelativePath,
  kPathTooLong,
  kResolutionDenied,
  kTargetMissing,
  kPermissionDenied,
  kNotRegularFile,
  kFileTooLarge,
  kProcUnavailable,
  kIoError,
};

struct PolicyError final {
  PolicyErrorCode code;
  std::string message;
};

struct FilesystemPolicyLimits final {
  std::size_t max_config_bytes = 64U * 1024U;
  std::size_t max_roots = 16U;
  std::size_t max_path_bytes = 4096U;
  std::uint64_t max_file_bytes = 1024ULL * 1024ULL * 1024ULL;
  bool allow_legacy_descriptor_walk = false;
};

struct RootPolicyConfig final {
  std::string name;
  std::string path;
  std::uint64_t max_file_bytes;
};

struct FilesystemPolicyConfig final {
  std::vector<RootPolicyConfig> roots;
};

struct ConfigParseResult final {
  std::optional<FilesystemPolicyConfig> config;
  std::optional<PolicyError> error;
};

class UniqueFd final {
 public:
  UniqueFd() noexcept = default;
  explicit UniqueFd(int fd) noexcept;
  ~UniqueFd();

  UniqueFd(const UniqueFd&) = delete;
  UniqueFd& operator=(const UniqueFd&) = delete;
  UniqueFd(UniqueFd&& other) noexcept;
  UniqueFd& operator=(UniqueFd&& other) noexcept;

  [[nodiscard]] int get() const noexcept;
  [[nodiscard]] bool valid() const noexcept;
  [[nodiscard]] int release() noexcept;
  void reset(int fd = -1) noexcept;

 private:
  int fd_ = -1;
};

class ReadOnlyFile final {
 public:
  ReadOnlyFile(UniqueFd fd, std::uint64_t observed_size,
               std::uint64_t max_read_bytes) noexcept;

  ReadOnlyFile(const ReadOnlyFile&) = delete;
  ReadOnlyFile& operator=(const ReadOnlyFile&) = delete;
  ReadOnlyFile(ReadOnlyFile&&) noexcept = default;
  ReadOnlyFile& operator=(ReadOnlyFile&&) noexcept = default;

  [[nodiscard]] int fd() const noexcept;
  [[nodiscard]] std::uint64_t observed_size() const noexcept;
  [[nodiscard]] std::uint64_t max_read_bytes() const noexcept;

 private:
  UniqueFd fd_;
  std::uint64_t observed_size_;
  std::uint64_t max_read_bytes_;
};

struct OpenFileResult final {
  std::optional<ReadOnlyFile> file;
  std::optional<PolicyError> error;
};

class FilesystemPolicy final {
 public:
  FilesystemPolicy() = default;
  ~FilesystemPolicy() = default;

  FilesystemPolicy(const FilesystemPolicy&) = delete;
  FilesystemPolicy& operator=(const FilesystemPolicy&) = delete;
  FilesystemPolicy(FilesystemPolicy&&) noexcept = default;
  FilesystemPolicy& operator=(FilesystemPolicy&&) noexcept = default;

  struct CreateResult;

  [[nodiscard]] static CreateResult create(
      const FilesystemPolicyConfig& config,
      FilesystemPolicyLimits limits = {});

  [[nodiscard]] OpenFileResult open_regular_file(
      std::string_view root_name, std::string_view relative_path) const;
  [[nodiscard]] std::size_t root_count() const noexcept;

 private:
  struct RootHandle final {
    std::string name;
    UniqueFd directory;
    std::uint64_t max_file_bytes;
  };

  explicit FilesystemPolicy(FilesystemPolicyLimits limits) noexcept;

  FilesystemPolicyLimits limits_{};
  std::vector<RootHandle> roots_;
};

struct FilesystemPolicy::CreateResult final {
  std::optional<FilesystemPolicy> policy;
  std::optional<PolicyError> error;
};

[[nodiscard]] ConfigParseResult parse_filesystem_policy_config(
    std::string_view text, FilesystemPolicyLimits limits = {});
[[nodiscard]] std::string_view policy_error_name(PolicyErrorCode code) noexcept;

}  // namespace native_mcp
