# Phase 3 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 3 — Streaming log-analysis tools
- Version: 0.4.0
- Prepared: 2026-07-18
- Baseline commit: `dced2ad919b49ae6d130cc372fcd36ce88f2ee4e`
- Baseline tag: `v0.3.0`
- Target: Linux with a C++20 compiler
- Protocol revision: `2025-11-25`

## Implemented

- Optional startup loading of the bounded Phase 2 filesystem policy.
- `logs.search` for bounded literal matching in one approved regular file.
- `logs.tail` for bounded previews of final logical lines.
- Streaming 8 KiB reads with a 16 MiB synchronous file ceiling.
- Search matching across chunk boundaries using a bounded KMP state machine.
- Fixed observed-size read budgets and file-change disclosure.
- Bounded escaped previews for binary and non-printable bytes.
- Closed tool input schemas and success output schemas.
- Read-only tool annotations and synchronous task metadata.
- Per-process tool-call burst limiting.
- Unit, protocol, malformed-input, policy-denial, and real-process tests.

## Explicitly not implemented

- Regex or recursive multi-file search.
- Arbitrary file reading outside configured named roots.
- Writable files, file creation, deletion, or mutation.
- Shell execution, HTTP, listening sockets, or other network access.
- ELF inspection or process observation.
- File watching or continuous log streaming.
- Coroutines, workers, cancellation, queues, or hard tool deadlines.
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
include/native_mcp/file_policy.hpp
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/log_analysis.hpp
include/native_mcp/log_tools.hpp
include/native_mcp/server.hpp
src/file_policy.cpp
src/foundation.cpp
src/json_rpc.cpp
src/log_analysis.cpp
src/log_tools.cpp
src/main.cpp
src/server.cpp
tests/file_policy_tests.cpp
tests/foundation_tests.cpp
tests/log_analysis_tests.cpp
tests/protocol_tests.cpp
tests/stdio_integration_tests.cpp
```

Builds, binaries, objects, Git metadata, credentials, local paths, archives, and
private material are excluded.
