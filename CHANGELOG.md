# Changelog

All notable changes are recorded here. The project follows semantic versioning after
the first stable release; pre-1.0 versions may change interfaces.

## [Unreleased]

## [0.8.0] - candidate

### Added

- Bounded SAX JSON preflight for syntax, nesting, token count, and duplicate keys.
- Five optional Clang libFuzzer targets for protocol, runtime policy, ELF, log, and bounded `/proc` parser paths.
- Deterministic mutation smoke runner shared by GCC, Clang, CTest, and sanitizer builds.
- Curated fuzz corpora, target-specific dictionaries, and native campaign scripts.
- Dedicated ThreadSanitizer build mode and repeated orchestration stress tests.
- Security regressions for hostile JSON, oversized lines, canonical numeric IDs,
  cancellation/deadline precedence, callback exceptions, and concurrent shutdown.
- Synthetic `/proc` parser unit tests for identity, status, page counters, aggregate rollups, and overflow rejection.
- ADR 0011 and a campaign guide documenting native fuzzing and regression policy.

### Changed

- Project version advanced to `0.8.0`.
- Runtime-policy JSON is limited to 32 nested containers and 4,096 tokens.
- Protocol JSON is limited to 64 nested containers and 32,768 tokens.
- Equal signed and unsigned non-negative JSON-RPC IDs share one in-flight identity.
- Scheduler construction now joins already-created workers if later thread creation fails.
- Scheduler shutdown is serialized and safe for simultaneous callers.
- CI adds leak-enabled ASan/UBSan fuzz smoke, focused ThreadSanitizer, and bounded
  libFuzzer jobs.

## [0.7.0] - 2026-07-18

### Added

- Fixed two-thread worker pool and bounded C++20 coroutine scheduling.
- Sixteen-call outstanding-work cap with explicit backpressure errors.
- MCP `notifications/cancelled` handling for in-flight tool requests.
- Cooperative stop contexts in log, ELF, and process analyzers.
- Thirty-second steady-clock deadlines and bounded timeout errors.
- Serialized multi-threaded protocol output and EOF draining.
- Scheduler tests for parallelism, saturation, duplicate IDs, cancellation, and deadlines.
- ADR 0010 documenting the orchestration boundary.

### Changed

- Project version advanced to `0.7.0`.
- Configured tool calls may complete out of request order and remain correlated by ID.
- MCP task execution remains explicitly forbidden.

## [0.6.0] - 2026-07-18

### Added

- Version-2 runtime policy with explicit symbolic process targets.
- Policy-gated `proc.memory` MCP tool for bounded aggregate `/proc` counters.
- Same-effective-UID enforcement and startup process identity capture.
- Strict pidfd pinning with an explicit old-kernel compatibility option.
- Pinned `/proc/<pid>` directory and start-time revalidation against PID reuse.
- Bounded `status`, `statm`, and optional `smaps_rollup` parsing.
- Process lifecycle, runtime-config, protocol, and real-process regression tests.
- ADR 0009 documenting the bounded process-memory observation boundary.

### Changed

- Project version advanced to `0.6.0`.
- Tool discovery is now capability-dependent for filesystem and process policies.
- Phase 4 ELF malformed-input and schema regressions are retained in the cumulative suite.

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
