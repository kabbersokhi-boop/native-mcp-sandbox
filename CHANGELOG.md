# Changelog

All notable changes are recorded here. The project follows semantic versioning after
the first stable release; pre-1.0 versions may change interfaces.

## [Unreleased]

## [0.5.0] - 2026-07-18

### Added

- Policy-gated `elf.inspect` MCP tool for bounded ELF32 and ELF64 metadata.
- Little- and big-endian ELF parsing without executing or memory-mapping targets.
- Bounded interpreter, dynamic dependency, GNU build-ID, and segment inspection.
- Structural stack, RELRO, PIE, and writable-executable segment indicators.
- Overflow-checked file-range validation and a 1 MiB metadata-read ceiling.
- Deterministic synthetic and real-process ELF tests.
- ADR 0008 documenting the safe ELF inspection boundary.

### Changed

- Project version advanced to `0.5.0`.
- The generic tool service now advertises log and ELF tools together.
- Third-party notices cover Phases 1 through 4.

## [0.4.0] - 2026-07-18

### Added

- Configured MCP exposure of `logs.search` and `logs.tail`.
- Streaming literal matching across read-chunk boundaries.
- Bounded final-line retention and escaped binary previews.
- Closed tool schemas, success output schemas, and read-only annotations.
- Fixed observed-size read budgets and file-change disclosure.
- Per-process tool-call burst limiting.
- Unit and real-process tests for configured tool execution.
- ADR 0007 documenting the Phase 3 log-tool boundary.

### Changed

- Project version advanced to `0.4.0`.
- Successful structured tool results conform to advertised output schemas.
- Compatibility descriptor walking classifies intermediate symlinks as resolution denials.


## [0.3.0] - 2026-07-18

### Added

- Bounded schema-v1 filesystem policy configuration parser.
- Named read-only roots with owned directory descriptors.
- Strict Linux `openat2` containment for traversal, symlink, magic-link, and mount
  crossing denial.
- Regular-file, read-permission, and per-root file-size enforcement.
- Pinned descriptor reopening through `/proc/self/fd`.
- Explicit opt-in descriptor-walk compatibility mode for old kernels.
- Adversarial filesystem policy unit tests.
- ADR 0006 documenting the descriptor-based security boundary.

### Changed

- Project version advanced to `0.3.0`.
- Documentation now distinguishes the implemented policy library from future MCP tools.

## [0.2.0] - 2026-07-18

### Added

- Bounded newline-delimited JSON-RPC 2.0 transport over stdin/stdout.
- MCP lifecycle support for protocol revision `2025-11-25`.
- `initialize`, `notifications/initialized`, `ping`, and empty `tools/list` handling.
- Structured parse, request, method, parameter, lifecycle, and size errors.
- Protocol unit tests and deterministic process-level stdio coverage.
- System nlohmann/json dependency documentation and attribution.
- ADRs for the JSON dependency and synchronous protocol baseline.

### Changed

- Project version advanced to `0.2.0`.
- Documentation distinguishes the protocol server from future host tools.
- CI installs nlohmann/json 3.11 or newer.

## [0.1.0] - 2026-07-18

### Added

- C++20 CMake project and low-memory build presets.
- Foundation executable with version and self-check commands.
- Validated conservative resource-budget model.
- Unit and command-level CTest coverage.
- GCC, Clang, and sanitizer CI jobs.
- Public architecture, threat model, security, contribution, and roadmap documents.
- ADRs for read-only scope, local stdio transport, and bounded defaults.
