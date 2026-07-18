#include "native_mcp/file_policy.hpp"
#include "native_mcp/foundation.hpp"
#include "native_mcp/log_tools.hpp"
#include "native_mcp/server.hpp"

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

namespace {

struct ToolLoadResult final {
  std::optional<native_mcp::LogToolService> tools;
  std::string error;
};

void print_usage(std::ostream& output) {
  output
      << "Usage: native-mcp-sandbox [--help | --version | --self-check]\n"
      << "       native-mcp-sandbox\n"
      << "       native-mcp-sandbox --policy-config FILE "
         "[--allow-legacy-descriptor-walk]\n"
      << "\n"
      << "With no arguments, run the MCP lifecycle server with no host tools.\n"
      << "With --policy-config, expose bounded read-only logs.search and logs.tail tools.\n"
      << "Strict openat2 containment is required unless the explicit legacy flag is used.\n"
      << "Diagnostics are written only to stderr.\n";
}

[[nodiscard]] ToolLoadResult load_tools(
    const std::string_view path, const bool allow_legacy_descriptor_walk) {
  native_mcp::FilesystemPolicyLimits limits;
  limits.allow_legacy_descriptor_walk = allow_legacy_descriptor_walk;

  const std::string config_path{path};
  native_mcp::UniqueFd descriptor{
      ::open(config_path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)};
  if (!descriptor.valid()) {
    return {.tools = std::nullopt,
            .error = "could not open the policy configuration as a regular file"};
  }

  struct stat before {};
  if (::fstat(descriptor.get(), &before) != 0 || !S_ISREG(before.st_mode) ||
      before.st_size < 0) {
    return {.tools = std::nullopt,
            .error = "policy configuration is not a readable regular file"};
  }
  const auto size = static_cast<std::uint64_t>(before.st_size);
  if (size > limits.max_config_bytes) {
    return {.tools = std::nullopt,
            .error = "policy configuration exceeds the startup byte limit"};
  }

  std::string text(static_cast<std::size_t>(size), '\0');
  std::size_t total = 0U;
  while (total < text.size()) {
    const ssize_t count =
        ::pread(descriptor.get(), text.data() + total, text.size() - total,
                static_cast<off_t>(total));
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return {.tools = std::nullopt,
              .error = "failed while reading the policy configuration"};
    }
    if (count == 0) {
      return {.tools = std::nullopt,
              .error = "policy configuration changed during startup"};
    }
    total += static_cast<std::size_t>(count);
  }

  struct stat after {};
  if (::fstat(descriptor.get(), &after) != 0 || after.st_dev != before.st_dev ||
      after.st_ino != before.st_ino || after.st_mode != before.st_mode ||
      after.st_size != before.st_size) {
    return {.tools = std::nullopt,
            .error = "policy configuration changed during startup"};
  }

  native_mcp::ConfigParseResult parsed =
      native_mcp::parse_filesystem_policy_config(text, limits);
  if (!parsed.config.has_value()) {
    return {.tools = std::nullopt,
            .error = parsed.error->message};
  }
  native_mcp::FilesystemPolicy::CreateResult created =
      native_mcp::FilesystemPolicy::create(*parsed.config, limits);
  if (!created.policy.has_value()) {
    return {.tools = std::nullopt,
            .error = created.error->message};
  }
  return {.tools = native_mcp::LogToolService{std::move(*created.policy)},
          .error = {}};
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc == 1) {
    return native_mcp::run_stdio(std::cin, std::cout, std::cerr);
  }

  if (argc == 2) {
    const std::string_view argument{argv[1]};
    if (argument == "--help") {
      print_usage(std::cout);
      return 0;
    }
    if (argument == "--version") {
      std::cout << native_mcp::project_name() << ' '
                << native_mcp::project_version() << '\n';
      return 0;
    }
    if (argument == "--self-check") {
      const auto budget = native_mcp::conservative_budget();
      if (!native_mcp::is_budget_valid(budget)) {
        std::cerr << "self-check failed: invalid default resource budget\n";
        return 1;
      }
      std::cout << "self-check passed: "
                << native_mcp::budget_summary(budget) << '\n';
      return 0;
    }
    std::cerr << "unknown option: " << argument << '\n';
    print_usage(std::cerr);
    return 64;
  }

  const bool valid_config_form =
      (argc == 3 || argc == 4) &&
      std::string_view{argv[1]} == "--policy-config" &&
      (argc == 3 ||
       std::string_view{argv[3]} == "--allow-legacy-descriptor-walk");
  if (!valid_config_form) {
    print_usage(std::cerr);
    return 64;
  }

  const bool allow_legacy = argc == 4;
  ToolLoadResult loaded = load_tools(argv[2], allow_legacy);
  if (!loaded.tools.has_value()) {
    std::cerr << "native-mcp-sandbox: policy startup failed: "
              << loaded.error << '\n';
    return 78;
  }
  if (allow_legacy) {
    std::cerr
        << "native-mcp-sandbox: warning: legacy descriptor walk enabled; "
           "bind-mount containment is incomplete\n";
  }
  return native_mcp::run_stdio(std::cin, std::cout, std::cerr,
                               native_mcp::conservative_budget(),
                               std::move(loaded.tools));
}
