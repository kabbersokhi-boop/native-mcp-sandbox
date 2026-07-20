# ADR 0011: Native fuzzing and security-regression evidence

- Status: proposed for Phase 7 audit
- Date: 2026-07-18

## Context

Native MCP Sandbox parses attacker-controlled JSON-RPC, runtime-policy JSON, log bytes,
and ELF metadata. It also coordinates cancellation, deadlines, worker threads, coroutine
frames, and serialized output. Unit tests cover intended behavior, but hand-written cases
alone are weak evidence against malformed structure, rare state transitions, integer
boundaries, and concurrency races.

The project must remain small, native, reproducible, and honest about assurance. A fuzzing
campaign is evidence from a particular corpus, duration, compiler, sanitizer, kernel, and
machine. It is not a proof that the implementation is safe.

## Decision

Phase 7 adds three complementary layers.

### Bounded JSON preflight

A SAX pass runs before JSON DOM construction. It rejects invalid syntax, duplicate keys,
excessive nesting, and excessive token counts. Protocol input is capped at 64 nested
containers and 32,768 tokens. Runtime-policy input is capped at 32 containers and 4,096
tokens. The byte limits from earlier phases remain authoritative.

The preflight is intentionally not a second schema language. Existing closed-schema
validation still decides which fields and values are accepted.

### Shared fuzz invariants

One support library exercises protocol, runtime-policy, log, ELF, and pure `/proc` text-parser paths. It checks
bounded responses, parseable server output, exclusive result/error outcomes, configured
collection limits, metadata-read budgets, and preview-size limits.

The same support code is used by:

- a deterministic mutation runner built by ordinary GCC and Clang test configurations;
- ASan/UBSan test and extended smoke runs; and
- five optional Clang libFuzzer entry points.

Curated corpora contain ordinary valid inputs, truncated structures, duplicate keys,
configuration variants, log evidence, ELF magic, a minimal ELF64 header, and representative bounded proc text. Any future
crash or hang must be minimized and retained as a regression seed or deterministic test.

### Concurrency and failure regressions

The scheduler gains a worker-thread factory seam used only to inject construction
failure. If a later worker cannot be created, already-started workers are stopped and
joined before the exception escapes. Shutdown calls are serialized so simultaneous
callers cannot join the same worker concurrently. Stress tests repeat bounded admission,
cancellation, deadline, completion-exception, and shutdown races. A dedicated
ThreadSanitizer build runs the focused scheduler tests.

## Native execution

The assurance workflow runs directly on Linux. No container runtime is required. This
keeps `openat2`, pidfd, procfs, thread scheduling, sanitizer, and filesystem behavior
visible rather than introducing an unrelated namespace layer.

## CI policy

Pull requests and `main` run:

- GCC Debug and Clang Release with warnings as errors;
- Clang ASan/UBSan with leak detection and deterministic fuzz smoke;
- focused GCC ThreadSanitizer orchestration tests; and
- bounded Clang libFuzzer corpus and mutation runs.

Longer local campaigns remain explicit scripts because CI time is finite. Campaign
artifacts are not source and must not be committed unless minimized into a deliberate
regression input.

## Consequences

Positive consequences:

- duplicate-key ambiguity and parser depth/token bombs fail before DOM construction;
- fuzz targets and deterministic tests share assertions instead of drifting;
- rare scheduler construction and shutdown paths become testable;
- sanitizer and race-detector expectations are reproducible;
- newly discovered failures have a defined path into permanent coverage.

Costs and limitations:

- JSON is parsed twice: bounded SAX preflight, then DOM construction;
- duplicate-key tracking allocates bounded memory proportional to accepted key tokens;
- fuzzing uses temporary regular files for log and ELF paths and is slower than a pure
  in-memory parser; the proc target remains byte-only and does not access host procfs;
- coverage is limited by the selected time and corpus;
- ThreadSanitizer and AddressSanitizer cannot be enabled in one binary;
- cooperative cancellation still cannot forcibly interrupt an arbitrary blocking kernel
  call or non-cooperative executor.

## Rejected alternatives

### Rely only on libFuzzer

Rejected because GCC builds and ordinary contributors would lose the adversarial smoke
suite, and libFuzzer availability would become a prerequisite for useful regression
coverage.

### Rely only on deterministic mutation

Rejected because deterministic mutation is reproducible but lacks libFuzzer's
coverage-guided exploration and minimization.

### Add a containerized test environment

Rejected because it does not solve a current requirement and can obscure the Linux host
semantics this project is intended to demonstrate.

### Claim sanitizer-clean means secure

Rejected. Sanitizers detect specific classes of failures in executed paths. Documentation
must report exact tools, versions, commands, duration, and limitations.
