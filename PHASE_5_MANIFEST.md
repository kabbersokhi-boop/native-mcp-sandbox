# Phase 5 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 5 — Bounded `/proc` memory observation
- Version: 0.6.0
- Prepared: 2026-07-18
- Baseline commit: `f67486270061dbdf0e345a6be3e637e79780d334`
- Baseline tag: `v0.5.0`
- Target: Linux with a C++20 compiler
- Protocol revision: `2025-11-25`

## Implemented

- Backward-compatible runtime-policy schema version 1 for filesystem-only tools.
- Closed runtime-policy schema version 2 with exact roots and process arrays.
- Operator-defined symbolic process aliases; MCP clients never submit raw PIDs.
- Same-effective-UID restriction for every configured process.
- Retained `/proc/<pid>` directory descriptors and recorded process start time.
- Strict pidfd-backed lifetime checks on supported Linux kernels.
- Explicit opt-in legacy process mode with start-time revalidation.
- Policy-gated `proc.memory` MCP tool for bounded aggregate memory counters.
- Fixed reads from status, statm, and optional smaps_rollup only.
- Overflow-checked page-count conversion and independently bounded pseudo-file reads.
- Capability-dependent tool discovery for filesystem-only, process-only, or combined mode.
- Unit, protocol, lifecycle, exited-process, and real-process integration tests.
- ADR 0009 documenting the process-observation boundary.

## Explicitly not implemented

- `/proc/<pid>/mem` access or raw target-memory contents.
- Memory maps, smaps entries, pagemap, command lines, environments, or file descriptors.
- Agent-selected numeric PIDs or unrestricted process discovery.
- Process signaling, suspension, mutation, injection, tracing, or debugging.
- Filesystem mutation, shell execution, HTTP, listeners, or other networking.
- ELF sections, symbols, relocations, DWARF, or disassembly.
- Coroutines, workers, cancellation, queues, backpressure, or hard deadlines.
- Namespace, Landlock, seccomp, or privilege-reduction enforcement.
- Performance benchmarks or comparison claims.

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
include/native_mcp/elf_analysis.hpp
include/native_mcp/file_policy.hpp
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/log_analysis.hpp
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
src/process_memory.cpp
src/runtime_config.cpp
src/server.cpp
src/tool_service.cpp
tests/elf_analysis_tests.cpp
tests/file_policy_tests.cpp
tests/foundation_tests.cpp
tests/log_analysis_tests.cpp
tests/process_memory_tests.cpp
tests/protocol_tests.cpp
tests/stdio_integration_tests.cpp
```

Builds, binaries, objects, Git metadata, credentials, local paths, and archives are
excluded.
