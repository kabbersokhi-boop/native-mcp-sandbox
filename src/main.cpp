#include "native_mcp/file_policy.hpp"
#include "native_mcp/foundation.hpp"
#include "native_mcp/process_memory.hpp"
#include "native_mcp/runtime_config.hpp"
#include "native_mcp/server.hpp"
#include "native_mcp/tool_service.hpp"

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
  std::optional<native_mcp::ToolService> tools;
  bool legacy_filesystem = false;
  bool legacy_process = false;
  std::string error;
};

struct StartupOptions final {
  std::string config_path;
  bool allow_legacy_descriptor_walk = false;
  bool allow_legacy_process_pinning = false;
};

void print_usage(std::ostream& output) {
  output
      << "Usage: native-mcp-sandbox [--help | --version | --self-check]\n"
      << "       native-mcp-sandbox\n"
      << "       native-mcp-sandbox --policy-config FILE "
         "[--allow-legacy-descriptor-walk] "
         "[--allow-legacy-process-pinning]\n"
      << "\n"
      << "With no arguments, run the MCP lifecycle server with no host tools.\n"
      << "With --policy-config, expose only explicitly configured read-only tools.\n"
      << "Schema version 1 configures filesystem tools; version 2 may also name\n"
      << "same-UID processes for bounded aggregate /proc memory observation.\n"
      << "Strict openat2 and pidfd pinning are required unless explicit legacy flags\n"
      << "are used. Diagnostics are written only to stderr.\n";
}

[[nodiscard]] std::optional<StartupOptions> parse_startup_options(
    const int argc, char* argv[]) {
  if (argc < 3 || argc > 5 || std::string_view{argv[1]} != "--policy-config") {
    return std::nullopt;
  }
  StartupOptions options{.config_path = argv[2]};
  for (int index = 3; index < argc; ++index) {
    const std::string_view flag{argv[index]};
    if (flag == "--allow-legacy-descriptor-walk" &&
        !options.allow_legacy_descriptor_walk) {
      options.allow_legacy_descriptor_walk = true;
    } else if (flag == "--allow-legacy-process-pinning" &&
               !options.allow_legacy_process_pinning) {
      options.allow_legacy_process_pinning = true;
    } else {
      return std::nullopt;
    }
  }
  return options;
}

[[nodiscard]] ToolLoadResult load_tools(const StartupOptions& options) {
  native_mcp::RuntimeConfigLimits limits;
  limits.filesystem.allow_legacy_descriptor_walk =
      options.allow_legacy_descriptor_walk;
  limits.processes.allow_legacy_process_pinning =
      options.allow_legacy_process_pinning;

  native_mcp::UniqueFd descriptor{
      ::open(options.config_path.c_str(),
             O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)};
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

  native_mcp::RuntimeConfigParseResult parsed =
      native_mcp::parse_runtime_policy_config(text, limits);
  if (!parsed.config.has_value()) {
    return {.tools = std::nullopt, .error = parsed.error->message};
  }

  std::optional<native_mcp::FilesystemPolicy> filesystem;
  if (!parsed.config->filesystem.roots.empty()) {
    native_mcp::FilesystemPolicy::CreateResult created =
        native_mcp::FilesystemPolicy::create(parsed.config->filesystem,
                                             limits.filesystem);
    if (!created.policy.has_value()) {
      return {.tools = std::nullopt, .error = created.error->message};
    }
    filesystem = std::move(*created.policy);
  }

  std::optional<native_mcp::ProcessPolicy> processes;
  bool legacy_process = false;
  if (!parsed.config->processes.processes.empty()) {
    native_mcp::ProcessPolicy::CreateResult created =
        native_mcp::ProcessPolicy::create(parsed.config->processes,
                                          limits.processes);
    if (!created.policy.has_value()) {
      return {.tools = std::nullopt, .error = created.error->message};
    }
    legacy_process = created.policy->uses_legacy_pinning();
    processes = std::move(*created.policy);
  }

  const bool legacy_filesystem =
      options.allow_legacy_descriptor_walk && filesystem.has_value();
  return {.tools = native_mcp::ToolService{std::move(filesystem),
                                            std::move(processes)},
          .legacy_filesystem = legacy_filesystem,
          .legacy_process = legacy_process,
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

  const auto options = parse_startup_options(argc, argv);
  if (!options.has_value()) {
    print_usage(std::cerr);
    return 64;
  }

  ToolLoadResult loaded = load_tools(*options);
  if (!loaded.tools.has_value()) {
    std::cerr << "native-mcp-sandbox: policy startup failed: "
              << loaded.error << '\n';
    return 78;
  }
  if (loaded.legacy_filesystem) {
    std::cerr
        << "native-mcp-sandbox: warning: legacy descriptor walk enabled; "
           "bind-mount containment is incomplete\n";
  }
  if (loaded.legacy_process) {
    std::cerr
        << "native-mcp-sandbox: warning: legacy process identity checks enabled; "
           "pidfd pinning is unavailable\n";
  }
  return native_mcp::run_stdio(std::cin, std::cout, std::cerr,
                               native_mcp::conservative_budget(),
                               std::move(loaded.tools));
}
