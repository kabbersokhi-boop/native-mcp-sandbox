# Phase 2 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 2 — Filesystem policy gate and resource enforcement
- Version: 0.3.0
- Prepared: 2026-07-18
- Baseline commit: `7f93e96c57f1e29a81d77b8bbd1ecc0ea3898537`
- Baseline tag: `v0.2.0`
- Target: Linux with a C++20 compiler
- Protocol revision: `2025-11-25`

## Implemented

- Bounded, closed-schema JSON filesystem policy configuration.
- Explicit named read-only roots and unique root-name enforcement.
- Absolute normalized root validation without symlink traversal.
- Strict Linux `openat2` target containment beneath a selected root.
- Denial of traversal, symbolic links, magic links, and mount crossings.
- Regular-file, read-permission, and per-root size enforcement.
- RAII ownership for root, path, and readable file descriptors.
- Pinned-inode reopening through `/proc/self/fd`.
- Fail-closed behavior when strict kernel support is unavailable.
- Explicit opt-in legacy descriptor-walk compatibility mode.
- Unit tests for malformed configuration and adversarial filesystem targets.

## Explicitly not implemented

- `tools/call` or any agent-reachable host access.
- Log search, ELF inspection, or process observation.
- Writable files, file creation, deletion, or mutation.
- Shell execution, HTTP, or listening network sockets.
- Namespace, Landlock, seccomp, or privilege-reduction enforcement.
- Coroutines, workers, cancellation, queues, or tool deadlines.
- Benchmarks or performance claims.

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
include/native_mcp/file_policy.hpp
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/server.hpp
src/file_policy.cpp
src/foundation.cpp
src/json_rpc.cpp
src/main.cpp
src/server.cpp
tests/file_policy_tests.cpp
tests/foundation_tests.cpp
tests/protocol_tests.cpp
tests/stdio_integration_tests.cpp
```

Builds, binaries, objects, Git metadata, credentials, local paths, and archives are
excluded.
