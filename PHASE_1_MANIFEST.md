# Phase 1 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 1 — Minimal MCP lifecycle and stdio transport
- Version: 0.2.0
- Prepared: 2026-07-18
- Baseline commit: `e94506d5e2b0a52ed00dd88dd0945b1ecad622fd`
- Target: Linux with a C++20 compiler
- Protocol revision: `2025-11-25`

## Implemented

- Bounded newline-delimited JSON-RPC 2.0 over stdin/stdout.
- MCP initialize negotiation and initialized lifecycle transition.
- Ping before and after initialization.
- Tool discovery after initialization, returning an empty tool array.
- Structured parse, invalid-request, method, parameter, lifecycle, request-size, and
  response-size errors.
- Clean EOF shutdown and CRLF input acceptance.
- Stdout protocol isolation and generic stderr diagnostics.
- Unit and deterministic process-level stdio integration tests.
- System-provided nlohmann/json 3.11 or newer.

## Explicitly not implemented

- `tools/call` or any analysis tool.
- Filesystem, log, ELF, process, shell, or network access.
- Filesystem allowlists or OS sandbox enforcement.
- JSON-RPC batching.
- HTTP or a listening socket.
- Coroutines, workers, cancellation, queue enforcement, or tool deadlines.
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
README.md
SECURITY.md
THIRD_PARTY_NOTICES.md
THREAT_MODEL.md
docs/adr/0001-security-first-read-only-scope.md
docs/adr/0002-local-stdio-transport.md
docs/adr/0003-bounded-low-memory-defaults.md
docs/adr/0004-system-nlohmann-json.md
docs/adr/0005-synchronous-phase-1-protocol.md
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/server.hpp
src/foundation.cpp
src/json_rpc.cpp
src/main.cpp
src/server.cpp
tests/foundation_tests.cpp
tests/protocol_tests.cpp
tests/stdio_integration_tests.cpp
```

Builds, binaries, objects, Git metadata, credentials, local paths, and archives are
excluded.
