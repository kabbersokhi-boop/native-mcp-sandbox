# Changelog

This file records important project changes.
The project uses semantic versioning after the first stable release.
Before version 1.0, an interface can change.

## Unreleased

### Changed

- Rewrote the active technical documentation in an ASD-STE100 Issue 9 aligned style.
- Added `docs/WRITING_STYLE.md` for future documentation changes.
- Kept legal, license, and third-party notice text unchanged.

### Phase 8 candidate

- Added a deterministic investigation demonstration for version `0.9.0`.
- Added committed synthetic evidence and canonical JSON and Markdown reports.
- Added strict standard-I/O, tool-list, response, schema, and report checks.
- CI assurance passed for implementation head `3db672ee65ebaca048d7e1f9490c6ad43aeb4ec4` in run `30007718678`.

## 0.8.0 - 2026-07-21

### Added

- Added bounded SAX JSON preflight for syntax, depth, token count, and duplicate keys.
- Added five optional Clang libFuzzer targets for protocol, runtime policy, ELF, log, and proc parser paths.
- Added one deterministic mutation runner for GCC, Clang, CTest, and sanitizer builds.
- Added curated corpora, target dictionaries, and native campaign scripts.
- Added a ThreadSanitizer build mode and repeated scheduler stress tests.
- Added regressions for hostile JSON, size limits, canonical IDs, cancellation, deadlines, callbacks, and shutdown.
- Added synthetic proc parser tests for identity, memory counters, page conversion, rollups, and overflow.
- Added ADR 0011 and the native fuzzing guide.
- Added the manual Extended Assurance workflow.

### Changed

- Changed the project version to `0.8.0`.
- Limited runtime-policy JSON to 32 nested containers and 4,096 tokens.
- Limited protocol JSON to 64 nested containers and 32,768 tokens.
- Gave equal non-negative signed and unsigned JSON-RPC IDs one in-flight identity.
- Made scheduler construction join earlier workers after a later worker-creation failure.
- Made worker-originated shutdown close admission without a wait or a join.
- Made a non-worker shutdown drain accepted work and join all workers.
- Added leak-enabled ASan and UBSan fuzz smoke, focused TSan, and bounded libFuzzer CI jobs.

### Assurance

- Normal GCC, Clang, ASan, UBSan, leak, TSan, and bounded libFuzzer CI passed.
- Two fixed-seed deterministic campaigns completed 100,000 iterations each.
- TSan unit tests passed 50 repetitions.
- TSan stress tests passed 25 repetitions.
- Strict `openat2`, pidfd, AF_UNIX, FIFO, and configured standard-I/O integration passed.
- Five 600-second libFuzzer campaigns completed 61,925,751 executions.
- The recorded campaigns found no crash, sanitizer finding, timeout, or crash artifact.

## 0.7.0 - 2026-07-18

### Added

- Added a fixed two-thread worker pool and bounded C++20 coroutine scheduling.
- Added a 16-call unfinished-work limit with explicit backpressure errors.
- Added MCP `notifications/cancelled` handling.
- Added cooperative stop checks to log, ELF, and process analyzers.
- Added 30-second steady-clock deadlines.
- Added serialized multi-threaded output and EOF draining.
- Added scheduler tests for parallel work, saturation, duplicate IDs, cancellation, and deadlines.
- Added ADR 0010.

### Changed

- Changed the project version to `0.7.0`.
- Permitted configured tool calls to finish out of request order.
- Kept MCP task execution forbidden.

## 0.6.0 - 2026-07-18

### Added

- Added runtime-policy schema version 2 with named process targets.
- Added the policy-gated `proc.memory` tool.
- Added same-effective-UID checks and startup process identity capture.
- Added strict pidfd pinning and an explicit old-kernel compatibility option.
- Added retained proc-directory descriptors and start-time checks.
- Added bounded parsing of `status`, `statm`, and optional `smaps_rollup`.
- Added process, policy, protocol, and integration tests.
- Added ADR 0009.

### Changed

- Changed the project version to `0.6.0`.
- Made tool discovery depend on the configured capabilities.
- Kept the Phase 4 ELF regressions in the cumulative test suite.

## 0.5.0 - 2026-07-18

### Added

- Added the policy-gated `elf.inspect` tool.
- Added little-endian and big-endian ELF32 and ELF64 parsing.
- Added bounded interpreter, dependency, build-ID, and segment analysis.
- Added stack, RELRO, PIE, and writable-executable segment indicators.
- Added checked file-range arithmetic and a 1 MiB metadata-read limit.
- Added synthetic and real-process ELF tests.
- Added ADR 0008.

### Changed

- Changed the project version to `0.5.0`.
- Made the tool service advertise log and ELF tools together.
- Updated the third-party notices for Phases 1 through 4.

## 0.4.0 - 2026-07-18

### Added

- Added configured MCP access to `logs.search` and `logs.tail`.
- Added literal matching across read-chunk boundaries.
- Added bounded final-line retention and escaped binary previews.
- Added closed tool schemas and read-only annotations.
- Added fixed read budgets and file-change reporting.
- Added a tool-call burst limit.
- Added unit and process integration tests.
- Added ADR 0007.

### Changed

- Changed the project version to `0.4.0`.
- Made successful tool results match the advertised output schemas.
- Made the compatibility walk report intermediate symbolic links as resolution denials.

## 0.3.0 - 2026-07-18

### Added

- Added a bounded schema-version-1 filesystem policy parser.
- Added named read-only roots with owned directory descriptors.
- Added strict `openat2` containment.
- Added denial of traversal, symbolic links, magic links, and mount crossings.
- Added regular-file, read-permission, and file-size checks.
- Added pinned descriptor reopening through `/proc/self/fd`.
- Added an explicit descriptor-walk compatibility mode.
- Added adversarial filesystem policy tests.
- Added ADR 0006.

### Changed

- Changed the project version to `0.3.0`.
- Clarified the difference between the policy library and later MCP tools.

## 0.2.0 - 2026-07-18

### Added

- Added bounded newline-delimited JSON-RPC 2.0 on standard input and standard output.
- Added MCP lifecycle support for revision `2025-11-25`.
- Added `initialize`, `notifications/initialized`, `ping`, and empty `tools/list` handling.
- Added structured protocol and size errors.
- Added protocol unit tests and process-level standard-I/O tests.
- Added nlohmann/json dependency documentation and attribution.
- Added ADRs for the JSON dependency and the synchronous protocol baseline.

### Changed

- Changed the project version to `0.2.0`.
- Clarified the difference between the protocol server and later host tools.
- Made CI install nlohmann/json 3.11 or newer.

## 0.1.0 - 2026-07-18

### Added

- Added the C++20 CMake project and low-memory presets.
- Added the foundation executable with version and self-check commands.
- Added the resource-budget model and validation.
- Added unit and command-level CTest tests.
- Added GCC, Clang, and sanitizer CI jobs.
- Added public architecture, threat model, security, contribution, roadmap, and ADR documents.
