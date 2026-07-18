# Phase 6 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 6 — Coroutine orchestration, cancellation, and backpressure
- Version: 0.7.0
- Prepared: 2026-07-18
- Baseline commit: `acccadfb4c8232d885c00cfc909abfc800539347`
- Baseline tag: `v0.6.0`
- Target: Linux with a C++20 compiler
- Protocol revision: `2025-11-25`

## Implemented

- Fixed two-thread worker pool for configured MCP tool calls.
- C++20 coroutine suspension and worker resumption with bounded pre-reserved handle storage.
- Sixteen-call cap covering queued and running tool requests.
- Bounded `server_busy` and duplicate in-flight request-ID errors.
- MCP `notifications/cancelled` parsing and response suppression.
- Cooperative `std::stop_token` checks in log, ELF, and process analyzers.
- Thirty-second steady-clock operation deadlines.
- Mutex-serialized complete JSON-RPC response lines from workers and the reader.
- EOF admission stop, accepted-work draining, and worker joining.
- Tests for parallel execution, queue saturation, duplicate IDs, cancellation, deadlines,
  analyzer stop checkpoints, malformed cancellation, and out-of-order responses.
- ADR 0010 documenting the orchestration and cancellation boundary.

## Preserved boundaries

- The same four policy-gated read-only tools from Phase 5.
- Strict `openat2` and pidfd modes by default.
- No client-selected absolute paths or numeric PIDs.
- No raw process memory, mappings, command lines, environments, or descriptors.
- No filesystem mutation, process control, shell execution, or networking.

## Explicitly not implemented

- Forced worker termination or hard real-time preemption.
- MCP tasks, durable jobs, task polling, or task result retrieval.
- Dynamic worker resizing, priorities, per-client fairness, or distributed queues.
- Regex, recursive search, file watching, ELF symbols, DWARF, or disassembly.
- Namespace, Landlock, seccomp, or privilege-reduction enforcement.
- Dedicated fuzzing campaign, performance benchmarks, or stable 1.0 interfaces.

## Expected source files

```text
.clang-format
.editorconfig
.github/workflows/ci.yml
.gitignore
ARCHITECTURE.md
CHANGELOG.md
CMakeLists.txt
CMakePresets.json
CODE_OF_CONDUCT.md
CONTRIBUTING.md
LICENSE
PHASE_0_MANIFEST.md
PHASE_1_MANIFEST.md
PHASE_2_MANIFEST.md
PHASE_3_MANIFEST.md
PHASE_4_MANIFEST.md
PHASE_5_MANIFEST.md
PHASE_6_MANIFEST.md
README.md
SECURITY.md
THIRD_PARTY_NOTICES.md
THREAT_MODEL.md
docs/adr/0001-security-first-read-only-scope.md
docs/adr/0002-local-stdio-transport.md
docs/adr/0003-bounded-low-memory-defaults.md
docs/adr/0004-system-nlohmann-json.md
docs/adr/0005-synchronous-phase-1-protocol.md
docs/adr/0006-openat2-filesystem-policy.md
docs/adr/0007-streaming-literal-log-tools.md
docs/adr/0008-bounded-elf-inspection.md
docs/adr/0009-bounded-proc-memory-observation.md
docs/adr/0010-bounded-coroutine-orchestration.md
include/native_mcp/elf_analysis.hpp
include/native_mcp/file_policy.hpp
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/log_analysis.hpp
include/native_mcp/operation.hpp
include/native_mcp/orchestration.hpp
include/native_mcp/process_memory.hpp
include/native_mcp/runtime_config.hpp
include/native_mcp/server.hpp
include/native_mcp/tool_service.hpp
src/elf_analysis.cpp
src/file_policy.cpp
src/foundation.cpp
src/json_rpc.cpp
src/log_analysis.cpp
src/main.cpp
src/orchestration.cpp
src/process_memory.cpp
src/runtime_config.cpp
src/server.cpp
src/tool_service.cpp
tests/elf_analysis_tests.cpp
tests/file_policy_tests.cpp
tests/foundation_tests.cpp
tests/log_analysis_tests.cpp
tests/orchestration_tests.cpp
tests/process_memory_tests.cpp
tests/protocol_tests.cpp
tests/stdio_integration_tests.cpp
```

Builds, binaries, objects, Git metadata, credentials, local paths, archives, and
non-source material are excluded.
