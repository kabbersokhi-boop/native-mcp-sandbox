# Phase 0 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 0 — Foundation
- Version: 0.1.0
- Prepared: 2026-07-18
- Target: Linux with a C++20 compiler

## Implemented

- Buildable C++20 static foundation library and command-line executable.
- Conservative resource-budget defaults and validation.
- `--help`, `--version`, and `--self-check` commands.
- Unit and command-level CTest tests.
- Development, sanitizer, and release CMake presets with two-job builds.
- GitHub Actions configuration for GCC, Clang, ASan, and UBSan.
- Public README, architecture, threat model, security policy, contribution guidance,
  code of conduct, changelog, and architecture decisions.

## Explicitly not implemented

- MCP or JSON-RPC parsing, transport, initialization, or tool discovery.
- Log, binary, ELF, or process-memory analysis.
- Coroutines, asynchronous I/O, worker execution, or cancellation.
- Filesystem sandbox enforcement or OS-level isolation.
- Performance benchmarks or Python comparison.

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
README.md
SECURITY.md
THREAT_MODEL.md
docs/adr/0001-security-first-read-only-scope.md
docs/adr/0002-local-stdio-transport.md
docs/adr/0003-bounded-low-memory-defaults.md
include/native_mcp/foundation.hpp
src/foundation.cpp
src/main.cpp
tests/foundation_tests.cpp
```

Build directories, compiler outputs, editor state, credentials, and repository
metadata are intentionally excluded from the release archive.
