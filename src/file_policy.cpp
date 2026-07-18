#include "native_mcp/file_policy.hpp"

#include <cerrno>
#include <cctype>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <linux/openat2.h>
#include <nlohmann/json.hpp>
#include <string>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <unordered_set>
#include <utility>

namespace native_mcp {
namespace {

using Json = nlohmann::json;

[[nodiscard]] PolicyError error(const PolicyErrorCode code,
                                std::string message) {
  return PolicyError{.code = code, .message = std::move(message)};
}

[[nodiscard]] bool valid_root_name(const std::string_view name) {
  if (name.empty() || name.size() > 64U) {
    return false;
  }
  for (const char raw_character : name) {
    const auto character = static_cast<unsigned char>(raw_character);
    if (!(std::isalnum(character) != 0 || character == '-' || character == '_')) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] bool valid_root_path(const std::string_view path,
                                   const std::size_t max_path_bytes) {
  if (path.empty() || path.front() != '/' || path.size() > max_path_bytes ||
      path.find('\0') != std::string_view::npos) {
    return false;
  }
  if (path == "/") {
    return true;
  }
  if (path.back() == '/') {
    return false;
  }
  std::size_t start = 1U;
  while (start <= path.size()) {
    const std::size_t slash = path.find('/', start);
    const std::size_t end = slash == std::string_view::npos ? path.size() : slash;
    const std::string_view component = path.substr(start, end - start);
    if (component.empty() || component == "." || component == "..") {
      return false;
    }
    if (slash == std::string_view::npos) {
      break;
    }
    start = slash + 1U;
  }
  return true;
}

[[nodiscard]] std::optional<PolicyError> validate_relative_path(
    const std::string_view path, const std::size_t max_path_bytes) {
  if (path.empty() || path.front() == '/' || path.back() == '/' ||
      path.find('\0') != std::string_view::npos) {
    return error(PolicyErrorCode::kInvalidRelativePath,
                 "path must be a nonempty relative file path");
  }
  if (path.size() > max_path_bytes) {
    return error(PolicyErrorCode::kPathTooLong,
                 "path exceeds the configured byte limit");
  }

  std::size_t start = 0U;
  while (start <= path.size()) {
    const std::size_t slash = path.find('/', start);
    const std::size_t end = slash == std::string_view::npos ? path.size() : slash;
    const std::string_view component = path.substr(start, end - start);
    if (component.empty() || component == "." || component == "..") {
      return error(PolicyErrorCode::kInvalidRelativePath,
                   "path contains an empty, dot, or parent component");
    }
    if (slash == std::string_view::npos) {
      break;
    }
    start = slash + 1U;
  }
  return std::nullopt;
}

[[nodiscard]] int openat2_path(const int directory_fd,
                               const std::string& path,
                               const std::uint64_t flags) {
  open_how how{};
  how.flags = flags;
  how.resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS |
                RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV;
  return static_cast<int>(::syscall(SYS_openat2, directory_fd, path.c_str(),
                                    &how, sizeof(how)));
}

[[nodiscard]] PolicyError map_open_error(const int number) {
  switch (number) {
    case ENOSYS:
    case E2BIG:
    case EINVAL:
      return error(PolicyErrorCode::kKernelUnsupported,
                   "required openat2 containment is unavailable");
    case ELOOP:
    case EXDEV:
      return error(PolicyErrorCode::kResolutionDenied,
                   "path resolution crossed a denied boundary");
    case ENOENT:
    case ENOTDIR:
      return error(PolicyErrorCode::kTargetMissing,
                   "target does not exist beneath the selected root");
    case EACCES:
    case EPERM:
      return error(PolicyErrorCode::kPermissionDenied,
                   "permission denied while opening target");
    default:
      return error(PolicyErrorCode::kIoError,
                   std::string{"open failed: "} + std::strerror(number));
  }
}


[[nodiscard]] int open_legacy_path(const int root_fd,
                                   const std::string_view path,
                                   PolicyError& failure) {
  UniqueFd current{::fcntl(root_fd, F_DUPFD_CLOEXEC, 0)};
  if (!current.valid()) {
    failure = error(PolicyErrorCode::kIoError, "failed to duplicate root descriptor");
    return -1;
  }

  std::size_t start = 0U;
  while (start < path.size()) {
    const std::size_t slash = path.find('/', start);
    const bool final = slash == std::string_view::npos;
    const std::size_t end = final ? path.size() : slash;
    const std::string component{path.substr(start, end - start)};
    const int flags = O_PATH | O_CLOEXEC | O_NOFOLLOW |
                      (final ? 0 : O_DIRECTORY);
    UniqueFd next{::openat(current.get(), component.c_str(), flags)};
    if (!next.valid()) {
      const int number = errno;
      if (number == ELOOP || number == ENOTDIR) {
        struct stat link_metadata {};
        if (::fstatat(current.get(), component.c_str(), &link_metadata,
                      AT_SYMLINK_NOFOLLOW) == 0 &&
            S_ISLNK(link_metadata.st_mode)) {
          failure = error(PolicyErrorCode::kResolutionDenied,
                          "legacy descriptor walk rejected a symbolic link");
          return -1;
        }
      }
      failure = map_open_error(number);
      return -1;
    }
    struct stat metadata {};
    if (::fstat(next.get(), &metadata) != 0) {
      failure = error(PolicyErrorCode::kIoError, "failed to inspect path component");
      return -1;
    }
    if (S_ISLNK(metadata.st_mode)) {
      failure = error(PolicyErrorCode::kResolutionDenied,
                      "legacy descriptor walk rejected a symbolic link");
      return -1;
    }
    if (!final && !S_ISDIR(metadata.st_mode)) {
      failure = error(PolicyErrorCode::kTargetMissing,
                      "path component is not a directory");
      return -1;
    }
    current = std::move(next);
    if (final) {
      return current.release();
    }
    start = slash + 1U;
  }
  failure = error(PolicyErrorCode::kInvalidRelativePath, "empty path");
  return -1;
}

[[nodiscard]] int open_root_legacy(const std::string_view path,
                                   PolicyError& failure) {
  UniqueFd current{::open("/", O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW)};
  if (!current.valid()) {
    failure = error(PolicyErrorCode::kOpenRootFailed,
                    "could not open filesystem root");
    return -1;
  }
  if (path == "/") {
    return current.release();
  }
  std::size_t start = 1U;
  while (start < path.size()) {
    const std::size_t slash = path.find('/', start);
    const bool final = slash == std::string_view::npos;
    const std::size_t end = final ? path.size() : slash;
    const std::string component{path.substr(start, end - start)};
    UniqueFd next{::openat(current.get(), component.c_str(),
                           O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW)};
    if (!next.valid()) {
      failure = error(PolicyErrorCode::kOpenRootFailed,
                      "configured root contains a missing, non-directory, or symlink component");
      return -1;
    }
    struct stat metadata {};
    if (::fstat(next.get(), &metadata) != 0 || !S_ISDIR(metadata.st_mode) ||
        S_ISLNK(metadata.st_mode)) {
      failure = error(PolicyErrorCode::kOpenRootFailed,
                      "configured root could not be validated");
      return -1;
    }
    current = std::move(next);
    if (final) {
      return current.release();
    }
    start = slash + 1U;
  }
  failure = error(PolicyErrorCode::kOpenRootFailed, "invalid root path");
  return -1;
}

[[nodiscard]] int open_root_strict(const std::string& path,
                                   const bool allow_legacy,
                                   PolicyError& failure) {
  open_how how{};
  how.flags = O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW;
  how.resolve = RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS;
  const int fd = static_cast<int>(
      ::syscall(SYS_openat2, AT_FDCWD, path.c_str(), &how, sizeof(how)));
  if (fd >= 0) {
    return fd;
  }
  const int number = errno;
  const bool unsupported = number == ENOSYS || number == E2BIG || number == EINVAL;
  if (unsupported && allow_legacy) {
    return open_root_legacy(path, failure);
  }
  if (unsupported) {
    failure = error(PolicyErrorCode::kKernelUnsupported,
                    "required openat2 root validation is unavailable");
  } else {
    failure = error(PolicyErrorCode::kOpenRootFailed,
                    "configured root contains a denied or inaccessible component");
  }
  return -1;
}

[[nodiscard]] bool same_object(const struct stat& left,
                               const struct stat& right) noexcept {
  return left.st_dev == right.st_dev && left.st_ino == right.st_ino &&
         left.st_mode == right.st_mode;
}

}  // namespace

UniqueFd::UniqueFd(const int fd) noexcept : fd_(fd) {}
UniqueFd::~UniqueFd() { reset(); }
UniqueFd::UniqueFd(UniqueFd&& other) noexcept : fd_(other.release()) {}
UniqueFd& UniqueFd::operator=(UniqueFd&& other) noexcept {
  if (this != &other) {
    reset(other.release());
  }
  return *this;
}
int UniqueFd::get() const noexcept { return fd_; }
bool UniqueFd::valid() const noexcept { return fd_ >= 0; }
int UniqueFd::release() noexcept {
  const int result = fd_;
  fd_ = -1;
  return result;
}
void UniqueFd::reset(const int fd) noexcept {
  if (fd_ >= 0) {
    (void)::close(fd_);
  }
  fd_ = fd;
}

ReadOnlyFile::ReadOnlyFile(UniqueFd fd, const std::uint64_t observed_size,
                           const std::uint64_t max_read_bytes) noexcept
    : fd_(std::move(fd)),
      observed_size_(observed_size),
      max_read_bytes_(max_read_bytes) {}
int ReadOnlyFile::fd() const noexcept { return fd_.get(); }
std::uint64_t ReadOnlyFile::observed_size() const noexcept { return observed_size_; }
std::uint64_t ReadOnlyFile::max_read_bytes() const noexcept { return max_read_bytes_; }

FilesystemPolicy::FilesystemPolicy(const FilesystemPolicyLimits limits) noexcept
    : limits_(limits) {}

FilesystemPolicy::CreateResult FilesystemPolicy::create(
    const FilesystemPolicyConfig& config, const FilesystemPolicyLimits limits) {
  if (config.roots.empty() || config.roots.size() > limits.max_roots) {
    return {.policy = std::nullopt,
            .error = error(PolicyErrorCode::kTooManyRoots,
                           "configuration must contain between one and the root limit")};
  }

  FilesystemPolicy policy{limits};
  std::unordered_set<std::string> names;
  for (const RootPolicyConfig& root : config.roots) {
    if (!valid_root_name(root.name)) {
      return {.policy = std::nullopt,
              .error = error(PolicyErrorCode::kInvalidRootName,
                             "root name contains unsupported characters")};
    }
    if (!valid_root_path(root.path, limits.max_path_bytes)) {
      return {.policy = std::nullopt,
              .error = error(PolicyErrorCode::kInvalidRootPath,
                             "root path must be absolute, bounded, and normalized")};
    }
    if (root.max_file_bytes == 0U || root.max_file_bytes > limits.max_file_bytes) {
      return {.policy = std::nullopt,
              .error = error(PolicyErrorCode::kFileTooLarge,
                             "root file limit is outside the accepted range")};
    }
    if (!names.insert(root.name).second) {
      return {.policy = std::nullopt,
              .error = error(PolicyErrorCode::kDuplicateRoot,
                             "root names must be unique")};
    }

    PolicyError root_error = error(PolicyErrorCode::kOpenRootFailed,
                                   "configured root could not be opened safely");
    UniqueFd directory{open_root_strict(
        root.path, limits.allow_legacy_descriptor_walk, root_error)};
    if (!directory.valid()) {
      return {.policy = std::nullopt, .error = std::move(root_error)};
    }
    struct stat metadata {};
    if (::fstat(directory.get(), &metadata) != 0 || !S_ISDIR(metadata.st_mode)) {
      return {.policy = std::nullopt,
              .error = error(PolicyErrorCode::kOpenRootFailed,
                             "configured root is not a directory")};
    }
    policy.roots_.push_back(RootHandle{.name = root.name,
                                       .directory = std::move(directory),
                                       .max_file_bytes = root.max_file_bytes});
  }

  return {.policy = std::move(policy), .error = std::nullopt};
}

OpenFileResult FilesystemPolicy::open_regular_file(
    const std::string_view root_name, const std::string_view relative_path) const {
  const RootHandle* root = nullptr;
  for (const RootHandle& candidate : roots_) {
    if (candidate.name == root_name) {
      root = &candidate;
      break;
    }
  }
  if (root == nullptr) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kUnknownRoot,
                           "requested root is not configured")};
  }
  if (const auto path_error =
          validate_relative_path(relative_path, limits_.max_path_bytes)) {
    return {.file = std::nullopt, .error = path_error};
  }

  const std::string path{relative_path};
  UniqueFd path_fd{openat2_path(root->directory.get(), path,
                                O_PATH | O_CLOEXEC | O_NOFOLLOW)};
  if (!path_fd.valid()) {
    const int openat2_error = errno;
    const bool unsupported = openat2_error == ENOSYS || openat2_error == E2BIG ||
                             openat2_error == EINVAL;
    if (!unsupported || !limits_.allow_legacy_descriptor_walk) {
      return {.file = std::nullopt, .error = map_open_error(openat2_error)};
    }
    PolicyError fallback_error = error(PolicyErrorCode::kIoError, "legacy open failed");
    path_fd.reset(open_legacy_path(root->directory.get(), path, fallback_error));
    if (!path_fd.valid()) {
      return {.file = std::nullopt, .error = std::move(fallback_error)};
    }
  }

  struct stat metadata {};
  if (::fstat(path_fd.get(), &metadata) != 0) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kIoError,
                           "failed to inspect opened target")};
  }
  // With O_PATH | O_NOFOLLOW, openat2 may return a descriptor for a
  // trailing symlink even when RESOLVE_NO_SYMLINKS is set. Reject it explicitly.
  if (S_ISLNK(metadata.st_mode)) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kResolutionDenied,
                           "target is a symbolic or magic link")};
  }
  if (!S_ISREG(metadata.st_mode)) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kNotRegularFile,
                           "target is not a regular file")};
  }
  if (metadata.st_size < 0 ||
      static_cast<std::uint64_t>(metadata.st_size) > root->max_file_bytes) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kFileTooLarge,
                           "target exceeds the configured file limit")};
  }

  const std::string descriptor_path =
      "/proc/self/fd/" + std::to_string(path_fd.get());
  UniqueFd readable{::open(descriptor_path.c_str(),
                           O_RDONLY | O_CLOEXEC | O_NONBLOCK)};
  if (!readable.valid()) {
    if (errno == EACCES || errno == EPERM) {
      return {.file = std::nullopt,
              .error = error(PolicyErrorCode::kPermissionDenied,
                             "permission denied reopening the pinned target")};
    }
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kProcUnavailable,
                           "could not reopen the pinned regular file through /proc/self/fd")};
  }

  struct stat readable_metadata {};
  if (::fstat(readable.get(), &readable_metadata) != 0 ||
      !same_object(metadata, readable_metadata) ||
      !S_ISREG(readable_metadata.st_mode)) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kIoError,
                           "reopened descriptor did not match the pinned target")};
  }
  if (readable_metadata.st_size < 0 ||
      static_cast<std::uint64_t>(readable_metadata.st_size) > root->max_file_bytes) {
    return {.file = std::nullopt,
            .error = error(PolicyErrorCode::kFileTooLarge,
                           "target grew beyond the configured file limit")};
  }

  return {.file = ReadOnlyFile{std::move(readable),
                               static_cast<std::uint64_t>(readable_metadata.st_size),
                               root->max_file_bytes},
          .error = std::nullopt};
}

std::size_t FilesystemPolicy::root_count() const noexcept { return roots_.size(); }

ConfigParseResult parse_filesystem_policy_config(
    const std::string_view text, const FilesystemPolicyLimits limits) {
  if (text.size() > limits.max_config_bytes) {
    return {.config = std::nullopt,
            .error = error(PolicyErrorCode::kConfigTooLarge,
                           "configuration exceeds the byte limit")};
  }

  Json document = Json::parse(text, nullptr, false);
  if (document.is_discarded() || !document.is_object() || document.size() != 2U ||
      !document.contains("version") || !document.contains("roots") ||
      !document["version"].is_number_unsigned() || document["version"] != 1U ||
      !document["roots"].is_array()) {
    return {.config = std::nullopt,
            .error = error(PolicyErrorCode::kInvalidConfig,
                           "configuration does not match schema version 1")};
  }
  if (document["roots"].empty() || document["roots"].size() > limits.max_roots) {
    return {.config = std::nullopt,
            .error = error(PolicyErrorCode::kTooManyRoots,
                           "configuration root count is outside the accepted range")};
  }

  FilesystemPolicyConfig config;
  for (const Json& value : document["roots"]) {
    if (!value.is_object() || value.size() != 3U || !value.contains("name") ||
        !value.contains("path") || !value.contains("maxFileBytes") ||
        !value["name"].is_string() || !value["path"].is_string() ||
        !value["maxFileBytes"].is_number_unsigned()) {
      return {.config = std::nullopt,
              .error = error(PolicyErrorCode::kInvalidConfig,
                             "root entry contains missing, extra, or invalid fields")};
    }
    const std::uint64_t file_limit = value["maxFileBytes"].get<std::uint64_t>();
    config.roots.push_back(RootPolicyConfig{
        .name = value["name"].get<std::string>(),
        .path = value["path"].get<std::string>(),
        .max_file_bytes = file_limit,
    });
  }

  return {.config = std::move(config), .error = std::nullopt};
}

std::string_view policy_error_name(const PolicyErrorCode code) noexcept {
  switch (code) {
    case PolicyErrorCode::kInvalidConfig: return "invalid_config";
    case PolicyErrorCode::kConfigTooLarge: return "config_too_large";
    case PolicyErrorCode::kTooManyRoots: return "root_count_invalid";
    case PolicyErrorCode::kInvalidRootName: return "invalid_root_name";
    case PolicyErrorCode::kInvalidRootPath: return "invalid_root_path";
    case PolicyErrorCode::kDuplicateRoot: return "duplicate_root";
    case PolicyErrorCode::kOpenRootFailed: return "open_root_failed";
    case PolicyErrorCode::kKernelUnsupported: return "kernel_unsupported";
    case PolicyErrorCode::kUnknownRoot: return "unknown_root";
    case PolicyErrorCode::kInvalidRelativePath: return "invalid_relative_path";
    case PolicyErrorCode::kPathTooLong: return "path_too_long";
    case PolicyErrorCode::kResolutionDenied: return "resolution_denied";
    case PolicyErrorCode::kTargetMissing: return "target_missing";
    case PolicyErrorCode::kPermissionDenied: return "permission_denied";
    case PolicyErrorCode::kNotRegularFile: return "not_regular_file";
    case PolicyErrorCode::kFileTooLarge: return "file_too_large";
    case PolicyErrorCode::kProcUnavailable: return "proc_unavailable";
    case PolicyErrorCode::kIoError: return "io_error";
  }
  return "unknown";
}

}  // namespace native_mcp
