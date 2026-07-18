#include "native_mcp/process_memory.hpp"
#include "native_mcp/runtime_config.hpp"

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <csignal>
#include <cstdlib>
#include <iostream>
#include <string>
#include <string_view>
#include <stop_token>

namespace {

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

native_mcp::ProcessPolicy create_self_policy(const bool allow_legacy = true) {
  native_mcp::ProcessPolicyConfig config;
  config.processes.push_back({.name = "server", .pid = std::nullopt});
  native_mcp::ProcessPolicyLimits limits;
  limits.allow_legacy_process_pinning = allow_legacy;
  auto created = native_mcp::ProcessPolicy::create(config, limits);
  if (!created.policy.has_value()) {
    std::cerr << "process policy error: " << created.error->message << '\n';
  }
  expect(created.policy.has_value(), "self process policy must be created");
  return std::move(*created.policy);
}

void test_runtime_config_versions() {
  const std::string version_one =
      R"({"version":1,"roots":[{"name":"logs","path":"/tmp","maxFileBytes":4096}]})";
  auto parsed = native_mcp::parse_runtime_policy_config(version_one);
  expect(parsed.config.has_value() && parsed.config->filesystem.roots.size() == 1U &&
             parsed.config->processes.processes.empty(),
         "version 1 filesystem configurations must remain compatible");

  const std::string version_two =
      R"({"version":2,"roots":[],"processes":[{"name":"server","pid":"self"}]})";
  parsed = native_mcp::parse_runtime_policy_config(version_two);
  expect(parsed.config.has_value() && parsed.config->filesystem.roots.empty() &&
             parsed.config->processes.processes.size() == 1U &&
             !parsed.config->processes.processes[0].pid.has_value(),
         "version 2 must support a process-only configuration");

  for (const std::string_view invalid : {
           R"({"version":2,"roots":[],"processes":[]})",
           R"({"version":2,"roots":[],"processes":[{"name":"p","pid":-1}]})",
           R"({"version":2,"roots":[],"processes":[{"name":"p","pid":1.5}]})",
           R"({"version":2,"roots":[],"processes":[{"name":"p","pid":18446744073709551616}]})",
           R"({"version":2,"roots":[],"processes":[{"name":"p","pid":"other"}]})",
           R"({"version":2,"roots":[],"processes":[{"name":"same","pid":"self"},{"name":"same","pid":"self"}]})",
           R"({"version":2,"roots":[],"processes":[{"name":"p","pid":"self","extra":true}]})",
           R"({"version":2,"roots":[],"processes":[],"extra":true})",
       }) {
    parsed = native_mcp::parse_runtime_policy_config(invalid);
    expect(parsed.error.has_value(),
           "malformed, signed, floating, overflowing, duplicate, and extra fields must fail closed");
  }

  native_mcp::RuntimeConfigLimits tiny;
  tiny.max_config_bytes = 8U;
  parsed = native_mcp::parse_runtime_policy_config(version_two, tiny);
  expect(parsed.error.has_value() &&
             parsed.error->code == native_mcp::RuntimeConfigErrorCode::kConfigTooLarge,
         "runtime configuration must be bounded before JSON parsing");
}

void test_self_memory_observation() {
  auto policy = create_self_policy();
  expect(policy.process_count() == 1U,
         "one configured process must be retained");

  auto observed = policy.inspect_memory("server");
  if (!observed.result.has_value()) {
    std::cerr << "process observation error: " << observed.error->message << '\n';
  }
  expect(observed.result.has_value(),
         "configured self memory observation must succeed");
  const auto& result = *observed.result;
  expect(result.pid == static_cast<std::uint32_t>(::getpid()) &&
             result.uid == static_cast<std::uint32_t>(::geteuid()),
         "process identity must match the pinned server process");
  expect(!result.name.empty() && !result.state.empty() && result.threads > 0U,
         "bounded status identity must be reported");
  expect(result.page_size_bytes > 0U && result.statm.virtual_bytes > 0U &&
             result.statm.resident_bytes > 0U,
         "statm page counters must be converted to bytes");
  expect(result.status.vm_size_bytes.has_value() &&
             result.status.vm_rss_bytes.has_value(),
         "selected status memory counters must be parsed");
  if (result.smaps_rollup_available) {
    expect(result.smaps_rollup.has_value() &&
               result.smaps_rollup->rss_bytes.has_value(),
           "available smaps_rollup data must contain aggregate memory counters");
  } else {
    expect(result.smaps_rollup_error.has_value(),
           "unavailable smaps_rollup must disclose a bounded error category");
  }

  observed = policy.inspect_memory("missing");
  expect(observed.error.has_value() &&
             observed.error->code ==
                 native_mcp::ProcessMemoryErrorCode::kUnknownProcess,
         "unknown symbolic process names must be rejected");
}

void test_pidfd_strict_or_fail_closed() {
  native_mcp::ProcessPolicyConfig config;
  config.processes.push_back({.name = "server", .pid = std::nullopt});
  auto created = native_mcp::ProcessPolicy::create(config);
  if (created.policy.has_value()) {
    const auto observed = created.policy->inspect_memory("server");
    expect(observed.result.has_value() && observed.result->pidfd_pinned,
           "strict process policy must use a pidfd when supported");
  } else {
    expect(created.error->code ==
               native_mcp::ProcessMemoryErrorCode::kKernelUnsupported,
           "strict mode may fail only when pidfd pinning is unavailable");
  }
}

void test_exited_process_is_not_rebound() {
  int ready_pipe[2]{-1, -1};
  expect(::pipe(ready_pipe) == 0, "failed to create child readiness pipe");
  const pid_t child = ::fork();
  expect(child >= 0, "failed to fork child process");
  if (child == 0) {
    (void)::close(ready_pipe[0]);
    const char ready = 'x';
    (void)::write(ready_pipe[1], &ready, 1U);
    (void)::close(ready_pipe[1]);
    for (;;) {
      ::pause();
    }
  }
  (void)::close(ready_pipe[1]);
  char ready = '\0';
  expect(::read(ready_pipe[0], &ready, 1U) == 1 && ready == 'x',
         "child process must reach the observation point");
  (void)::close(ready_pipe[0]);

  native_mcp::ProcessPolicyConfig config;
  config.processes.push_back(
      {.name = "child", .pid = static_cast<std::uint32_t>(child)});
  native_mcp::ProcessPolicyLimits limits;
  limits.allow_legacy_process_pinning = true;
  auto created = native_mcp::ProcessPolicy::create(config, limits);
  expect(created.policy.has_value(), "live same-UID child must be configurable");

  expect(::kill(child, SIGKILL) == 0, "failed to terminate child fixture");
  int status = 0;
  expect(::waitpid(child, &status, 0) == child,
         "failed to reap child fixture");
  const auto observed = created.policy->inspect_memory("child");
  expect(observed.error.has_value() &&
             (observed.error->code ==
                  native_mcp::ProcessMemoryErrorCode::kProcessMissing ||
              observed.error->code ==
                  native_mcp::ProcessMemoryErrorCode::kProcessChanged),
         "an exited configured process must never resolve to a reused PID");
}

}  // namespace

void test_operation_stop_context() {
  auto policy = create_self_policy();
  std::stop_source source;
  (void)source.request_stop();
  const native_mcp::OperationContext cancelled{
      source.get_token(), native_mcp::OperationContext::Clock::time_point::max()};
  const auto observed = policy.inspect_memory("server", cancelled);
  expect(observed.error.has_value() &&
             observed.error->code == native_mcp::ProcessMemoryErrorCode::kCancelled,
         "process observation must honor cooperative cancellation before proc reads");
}

int main() {
  test_runtime_config_versions();
  test_self_memory_observation();
  test_pidfd_strict_or_fail_closed();
  test_exited_process_is_not_rebound();
  test_operation_stop_context();
  std::cout << "All process memory tests passed\n";
  return EXIT_SUCCESS;
}
