# Changelog

This file records notable project changes.

The project follows semantic versioning before 1.0 with the usual caveat that interfaces can still change.

## Unreleased

### Fixed

- Aligned the external Python MCP client with revision `2025-11-25` used by the native server.
- Accepted the native server's complete bounded tool metadata and successful `structuredContent` results while preserving closed validation.
- Captured and validated advertised output schemas before admitting native tool evidence.
- Added a real-process contract check that drives the actual Python client against the actual C++ server and executes `logs.search`.
- Negotiated the server-supported MCP revision during initialization and rejected null JSON-RPC request IDs.
- Extended redaction through frozen tuple-backed arrays so nested structured evidence cannot bypass secret filtering.

## 0.11.0

### Added

- Added the external investigation agent in Python.
- Added provider-neutral closed request, response, failure, retry, transcript and redaction contracts.
- Added bounded MCP child-process orchestration with exact tool-surface capture, serial execution, stable action identity, replay rejection and at-most-once behavior.
- Added deterministic adversarial assurance for malformed input, fabricated evidence, correlation attacks, replay, secret leakage, endpoint policy, transcript tampering and budget boundaries.
- Added an optional configurable OpenAI-compatible non-streaming adapter for the external agent.
- Added verified-HTTPS production transport, DNS destination checks, redirect rejection, bounded response reading and classified retry behavior.
- Added project-authorized synthetic-only egress and a credential-free loopback fake-provider path.
- Added an opt-in, synthetic, redacted and non-gating hosted-provider smoke command.
- Added public demonstration and assurance guides.

### Changed

- Updated `README.md`, `ARCHITECTURE.md`, `SECURITY.md` and `THREAT_MODEL.md` to describe the released external-agent system and its authority boundaries.
- Clarified that the native C++ server remains stdio-only, network-free, credential-free and unchanged in tool authority.
- Added an engineering highlights guide, release procedure, documentation-integrity check and focused issue forms.
- Pinned GitHub Actions to immutable official commits and added Dependabot coverage for action updates.

### Assurance

The `v0.11.0` release candidate passed:

- 16 hosted-provider adapter tests;
- 34 adversarial provider-boundary tests;
- 32 orchestration tests;
- 25 contract tests and 10 security regressions;
- 21/21 CTest cases in dev, sanitizer and ThreadSanitizer presets;
- 100,000 deterministic fuzz iterations;
- five 2,000-run libFuzzer smoke campaigns.

Exact-head CI evidence is recorded in [`docs/ASSURANCE.md`](docs/ASSURANCE.md).

## 0.10.1

### Fixed

- Corrected the compiled project version after the immutable `v0.10.0` tag retained an older identifier.
- Strengthened benchmark metadata capture and offline schema validation.
- Added version-output regression coverage and recorded the independent correction audit.

### Security

- Preserved the native server boundary and documented that future provider access must remain in a separate external process.

## 0.10.0

### Added

- Added bounded reproducibility benchmarks and report validation.
- Added benchmark metadata, failure and invariant tests.
- Recorded the completed deterministic investigation demonstration as release evidence.

### Note

The immutable tag contains the historical stale compiled version identifier. `v0.10.1` is the correction release.

## 0.9.0

### Added

- Added the deterministic investigation demonstration using the real stdio MCP server.
- Added committed synthetic evidence and canonical JSON and Markdown reports.
- Added strict lifecycle, tool-list, response, schema, output-flood and forbidden-field checks.
- Added repeated byte-equality verification for generated reports.

## 0.8.0 - 2026-07-21

### Added

- Added bounded SAX JSON preflight for syntax, depth, token count and duplicate keys.
- Added five optional Clang libFuzzer targets for protocol, runtime policy, ELF, log and proc-parser paths.
- Added a deterministic mutation runner for normal and sanitizer builds.
- Added curated corpora, dictionaries, a ThreadSanitizer build and scheduler stress tests.
- Added regressions for hostile JSON, size limits, canonical IDs, cancellation, deadlines, callbacks and shutdown.

### Changed

- Limited runtime-policy JSON to 32 nested containers and 4,096 tokens.
- Limited protocol JSON to 64 nested containers and 32,768 tokens.
- Made scheduler construction and shutdown exception-safe.

### Assurance

- Recorded two 100,000-iteration deterministic campaigns.
- Recorded repeated ThreadSanitizer, strict `openat2`, pidfd, AF_UNIX, FIFO and configured stdio tests.
- Recorded five 600-second libFuzzer campaigns totaling 61,925,751 executions with no observed crash, sanitizer finding, timeout or crash artifact.

## 0.7.0 - 2026-07-18

### Added

- Added a fixed two-thread worker pool and bounded C++20 coroutine scheduling.
- Added unfinished-work backpressure, MCP cancellation, steady-clock deadlines and serialized output.
- Added scheduler tests for parallel work, saturation, duplicate IDs, cancellation and deadlines.

## 0.6.0 - 2026-07-18

### Added

- Added runtime-policy schema version 2 with named process targets.
- Added the policy-gated `proc.memory` tool.
- Added same-UID checks, proc-directory retention, start-time validation and strict pidfd pinning.
- Added bounded parsing of `status`, `statm` and optional `smaps_rollup`.

## 0.5.0 - 2026-07-18

### Added

- Added the policy-gated `elf.inspect` tool.
- Added bounded ELF32/ELF64 metadata parsing, build-ID and dependency inspection, and security-property indicators.
- Added checked file-range arithmetic and synthetic/real-process ELF tests.

## 0.4.0 - 2026-07-18

### Added

- Added configured MCP access to `logs.search` and `logs.tail`.
- Added literal matching across chunks, bounded tail previews, closed tool schemas and read-only annotations.
- Added fixed read budgets, file-change reporting and a tool-call burst limit.

## 0.3.0 - 2026-07-18

### Added

- Added a bounded filesystem policy parser with named read-only roots.
- Added strict `openat2` containment and denial of traversal, symlinks, magic links and mount crossings.
- Added descriptor pinning and an explicit compatibility walk.

## 0.2.0 - 2026-07-18

### Added

- Added bounded newline-delimited JSON-RPC 2.0 over stdio.
- Added MCP initialize, initialized notification, ping and empty `tools/list` lifecycle support.
- Added structured protocol errors, input limits and process-level integration tests.

## 0.1.0 - 2026-07-18

### Added

- Added the C++20 CMake project, foundation executable, resource-budget model and validation.
- Added unit and command-level tests, GCC/Clang CI and sanitizer configurations.
- Added the initial public architecture, security, threat-model, contribution and ADR documents.
