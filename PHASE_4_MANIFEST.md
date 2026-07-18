# Phase 4 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 4 — Safe Linux ELF inspection
- Version: 0.5.0
- Prepared: 2026-07-18
- Baseline commit: `ad4d6a70bf833c188d261b7221f01acfc2f9fa84`
- Baseline tag: `v0.4.0`
- Target: Linux with a C++20 compiler
- Protocol revision: `2025-11-25`

## Implemented

- Policy-gated `elf.inspect` alongside the existing Phase 3 log tools.
- ELF32 and ELF64 identification in little- and big-endian form.
- Bounded ELF header and program-header validation.
- Bounded interpreter, dynamic dependency, and GNU build-ID inspection.
- Segment summaries and structural stack, RELRO, PIE, and W+X indicators.
- Overflow-checked file-range arithmetic against the captured read budget.
- A 1 MiB total selected-metadata read ceiling with narrower structure limits.
- No execution, relocation, dynamic loading, shell invocation, or target mapping.
- Synthetic valid, malformed, bounded, protocol, and real-process tests.
- Generic tool-service naming for the combined log and ELF tool set.
- ADR 0008 documenting the ELF inspection boundary.

## Explicitly not implemented

- ELF section tables, symbols, relocations, DWARF, or disassembly.
- Signature verification, malware classification, or safety verdicts.
- Arbitrary file reading outside configured named roots.
- Writable files, creation, deletion, or mutation.
- Shell execution, HTTP, listening sockets, or other network access.
- Process memory or `/proc` observation tools.
- File watching, recursive search, or regex.
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
PHASE_4_MANIFEST.md
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
include/native_mcp/elf_analysis.hpp
include/native_mcp/file_policy.hpp
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/log_analysis.hpp
include/native_mcp/server.hpp
include/native_mcp/tool_service.hpp
src/elf_analysis.cpp
src/file_policy.cpp
src/foundation.cpp
src/json_rpc.cpp
src/log_analysis.cpp
src/main.cpp
src/server.cpp
src/tool_service.cpp
tests/elf_analysis_tests.cpp
tests/file_policy_tests.cpp
tests/foundation_tests.cpp
tests/log_analysis_tests.cpp
tests/protocol_tests.cpp
tests/stdio_integration_tests.cpp
```

Builds, binaries, objects, Git metadata, credentials, local paths, archives, and
private development material are excluded.
