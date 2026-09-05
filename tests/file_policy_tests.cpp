#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>

#include "native_mcp/file_policy.hpp"

namespace {

namespace fs = std::filesystem;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

class TempDirectory final {
 public:
  TempDirectory() {
    const char* base = std::getenv("NMS_TEST_TMPDIR");
    if (base == nullptr || *base == '\0') {
      base = std::getenv("TMPDIR");
    }
    if (base == nullptr || *base == '\0') {
      base = "/tmp";
    }
    fs::path base_path{base};
    std::error_code base_error;
    if (!base_path.is_absolute() || !fs::is_directory(base_path, base_error)) {
      base_path = "/tmp";
    }
    std::string pattern = (base_path / "nms-test-XXXXXX").string();
    // Reserve space for the longest Unix-socket fixture name created below.
    if (pattern.size() + sizeof("/socket") >= sizeof(sockaddr_un{}.sun_path)) {
      pattern = "/tmp/nms-test-XXXXXX";
    }
    pattern.push_back('\0');
    char* created = ::mkdtemp(pattern.data());
    expect(created != nullptr, "failed to create temporary directory");
    path_ = created;
  }
  ~TempDirectory() {
    std::error_code ignored;
    fs::remove_all(path_, ignored);
  }
  TempDirectory(const TempDirectory&) = delete;
  TempDirectory& operator=(const TempDirectory&) = delete;
  [[nodiscard]] const fs::path& path() const noexcept { return path_; }

 private:
  fs::path path_;
};

native_mcp::FilesystemPolicy create_policy(const fs::path& root,
                                            const std::uint64_t max_bytes = 1024U,
                                            const bool allow_legacy = false) {
  native_mcp::FilesystemPolicyConfig config;
  config.roots.push_back({.name = "evidence", .path = root.string(), .max_file_bytes = max_bytes});
  native_mcp::FilesystemPolicyLimits limits;
  limits.allow_legacy_descriptor_walk = allow_legacy;
  auto result = native_mcp::FilesystemPolicy::create(config, limits);
  if (!result.policy.has_value() && !allow_legacy && result.error.has_value() &&
      result.error->code == native_mcp::PolicyErrorCode::kKernelUnsupported) {
    limits.allow_legacy_descriptor_walk = true;
    result = native_mcp::FilesystemPolicy::create(config, limits);
  }
  expect(result.policy.has_value(), "valid policy must be created");
  return std::move(*result.policy);
}

void test_config_parser() {
  const std::string text =
      R"({"version":1,"roots":[{"name":"logs","path":"/tmp","maxFileBytes":4096}]})";
  auto parsed = native_mcp::parse_filesystem_policy_config(text);
  expect(parsed.config.has_value(), "valid configuration must parse");
  expect(parsed.config->roots.size() == 1U, "one root must be parsed");

  parsed = native_mcp::parse_filesystem_policy_config(R"({"version":1,"roots":[],"extra":true})");
  expect(parsed.error.has_value(), "unknown top-level fields must fail closed");

  for (
      const std::string_view invalid : {
          R"({"version":-1,"roots":[]})",
          R"({"version":1.0,"roots":[]})",
          R"({"version":18446744073709551616,"roots":[]})",
          R"({"version":1,"roots":[{"name":"logs","path":"/tmp","maxFileBytes":-1}]})",
          R"({"version":1,"roots":[{"name":"logs","path":"/tmp","maxFileBytes":1.5}]})",
          R"({"version":1,"roots":[{"name":"logs","path":"/tmp","maxFileBytes":18446744073709551616}]})",
      }) {
    parsed = native_mcp::parse_filesystem_policy_config(invalid);
    expect(parsed.error.has_value(),
           "signed, floating, and overflowing schema numbers must be rejected");
  }

  native_mcp::FilesystemPolicyConfig non_normalized;
  non_normalized.roots.push_back({"bad", "/tmp/../etc", 64U});
  native_mcp::FilesystemPolicyLimits compatibility_limits;
  compatibility_limits.allow_legacy_descriptor_walk = true;
  auto invalid_policy = native_mcp::FilesystemPolicy::create(non_normalized, compatibility_limits);
  expect(invalid_policy.error.has_value() &&
             invalid_policy.error->code == native_mcp::PolicyErrorCode::kInvalidRootPath,
         "non-normalized root paths must be rejected");

  native_mcp::FilesystemPolicyLimits limits;
  limits.max_config_bytes = 8U;
  parsed = native_mcp::parse_filesystem_policy_config(text, limits);
  expect(parsed.error.has_value() &&
             parsed.error->code == native_mcp::PolicyErrorCode::kConfigTooLarge,
         "oversized configuration must be rejected before parsing");
}

void test_policy_creation() {
  TempDirectory directory;
  native_mcp::FilesystemPolicyConfig duplicate;
  duplicate.roots.push_back({"same", directory.path().string(), 64U});
  duplicate.roots.push_back({"same", directory.path().string(), 64U});
  native_mcp::FilesystemPolicyLimits compatibility_limits;
  compatibility_limits.allow_legacy_descriptor_walk = true;
  auto created = native_mcp::FilesystemPolicy::create(duplicate, compatibility_limits);
  expect(created.error.has_value() &&
             created.error->code == native_mcp::PolicyErrorCode::kDuplicateRoot,
         "duplicate root names must be rejected");

  const fs::path link = directory.path().parent_path() / "native-mcp-root-link";
  std::error_code ignored;
  fs::remove(link, ignored);
  fs::create_directory_symlink(directory.path(), link);
  native_mcp::FilesystemPolicyConfig symlink_root;
  symlink_root.roots.push_back({"link", link.string(), 64U});
  created = native_mcp::FilesystemPolicy::create(symlink_root, compatibility_limits);
  expect(created.error.has_value(), "symlink roots must be rejected");
  fs::remove(link, ignored);

  const fs::path child = directory.path() / "child";
  fs::create_directory(child);
  fs::create_directory_symlink(directory.path(), link);
  symlink_root.roots.clear();
  symlink_root.roots.push_back({"link", (link / "child").string(), 64U});
  created = native_mcp::FilesystemPolicy::create(symlink_root, compatibility_limits);
  expect(created.error.has_value(), "configured roots with intermediate symlinks must be rejected");
  fs::remove(link, ignored);
}

void test_regular_file_and_denials() {
  TempDirectory directory;
  const int socket_fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  expect(socket_fd >= 0, "failed to create Unix socket fixture");
  const fs::path socket_path = directory.path() / "socket";
  sockaddr_un socket_address{};
  socket_address.sun_family = AF_UNIX;
  expect(socket_path.string().size() < sizeof(socket_address.sun_path),
         "socket fixture path must fit sockaddr_un");
  std::strcpy(socket_address.sun_path, socket_path.c_str());
  if (::bind(socket_fd, reinterpret_cast<const sockaddr*>(&socket_address),
             sizeof(socket_address)) != 0) {
    fail(std::string{"failed to bind Unix socket fixture at "} +
         socket_path.string() + ": " + std::strerror(errno));
  }
  fs::create_directories(directory.path() / "nested");
  {
    std::ofstream output(directory.path() / "nested" / "allowed.log");
    output << "bounded evidence\n";
  }
  {
    std::ofstream output(directory.path() / "oversized.log");
    output << std::string(128U, 'x');
  }
  fs::create_symlink("nested/allowed.log", directory.path() / "link.log");
  fs::create_directory_symlink("nested", directory.path() / "linked-dir");
  expect(::mkfifo((directory.path() / "pipe").c_str(), 0600) == 0,
         "failed to create FIFO fixture");

  auto policy = create_policy(directory.path(), 64U);
  auto opened = policy.open_regular_file("evidence", "nested/allowed.log");
  if (!opened.file.has_value()) {
    std::cerr << "open error: " << opened.error->message << " ("
              << native_mcp::policy_error_name(opened.error->code) << ")\n";
  }
  expect(opened.file.has_value(), "approved regular file must open");
  expect(opened.file->max_read_bytes() == 64U,
         "returned descriptor must retain the configured read budget");
  struct stat expected_metadata{};
  struct stat opened_metadata{};
  expect(::stat((directory.path() / "nested" / "allowed.log").c_str(), &expected_metadata) == 0 &&
             ::fstat(opened.file->fd(), &opened_metadata) == 0 &&
             expected_metadata.st_dev == opened_metadata.st_dev &&
             expected_metadata.st_ino == opened_metadata.st_ino,
         "readable descriptor must refer to the checked inode");
  expect(opened.file->observed_size() == 17U, "observed file size must be reported");

  opened = policy.open_regular_file("missing", "nested/allowed.log");
  expect(
      opened.error.has_value() && opened.error->code == native_mcp::PolicyErrorCode::kUnknownRoot,
      "unknown roots must be rejected");

  for (const std::string path : {"/etc/passwd", "../outside", "nested/../allowed.log",
                                 "./nested/allowed.log", "nested//allowed.log"}) {
    opened = policy.open_regular_file("evidence", path);
    expect(opened.error.has_value(), "unsafe relative path must be rejected");
  }

  opened = policy.open_regular_file("evidence", "link.log");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kResolutionDenied,
         "final symlink must be rejected");

  opened = policy.open_regular_file("evidence", "linked-dir/allowed.log");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kResolutionDenied,
         "intermediate symlink must be rejected");

  opened = policy.open_regular_file("evidence", "nested");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kNotRegularFile,
         "directories must be rejected");

  opened = policy.open_regular_file("evidence", "pipe");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kNotRegularFile,
         "FIFOs must be rejected without blocking");

  opened = policy.open_regular_file("evidence", "socket");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kNotRegularFile,
         "Unix sockets must be rejected without connecting");

  opened = policy.open_regular_file("evidence", "oversized.log");
  expect(
      opened.error.has_value() && opened.error->code == native_mcp::PolicyErrorCode::kFileTooLarge,
      "oversized regular files must be rejected");

  opened = policy.open_regular_file("evidence", "does-not-exist");
  expect(
      opened.error.has_value() && opened.error->code == native_mcp::PolicyErrorCode::kTargetMissing,
      "missing targets must be rejected");
  (void)::close(socket_fd);
}

void test_device_denial() {
  if (!fs::exists("/dev/null")) {
    return;
  }
  auto policy = create_policy("/dev", 1024U);
  const auto opened = policy.open_regular_file("evidence", "null");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kNotRegularFile,
         "device nodes must be rejected");
}

void test_mount_crossing_denial() {
  if (!fs::exists("/proc/version")) {
    return;
  }
  native_mcp::FilesystemPolicyConfig config;
  config.roots.push_back({"evidence", "/", 1024U * 1024U});
  auto created = native_mcp::FilesystemPolicy::create(config);
  if (created.error.has_value()) {
    expect(created.error->code == native_mcp::PolicyErrorCode::kKernelUnsupported,
           "strict mode may fail only because openat2 is unavailable");
    return;
  }
  expect(created.policy.has_value(), "root policy must be created");
  const auto opened = created.policy->open_regular_file("evidence", "proc/version");
  expect(opened.error.has_value() &&
             opened.error->code == native_mcp::PolicyErrorCode::kResolutionDenied,
         "strict mode must reject mount crossing");
}

}  // namespace

int main() {
  test_config_parser();
  test_policy_creation();
  test_regular_file_and_denials();
  test_device_denial();
  test_mount_crossing_denial();
  std::cout << "All filesystem policy tests passed\n";
  return EXIT_SUCCESS;
}
