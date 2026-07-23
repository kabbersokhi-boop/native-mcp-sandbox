# ADR 0011: Native fuzzing and security regression evidence

- Status: Accepted
- Date: 2026-07-20

## Context

Native MCP Sandbox parses untrusted protocol JSON, policy JSON, log data, and ELF data.
It also controls cancellation, deadlines, worker threads, coroutine frames, and serialized output.
Unit tests cover intended behavior.
Hand-written tests alone give limited evidence for rare malformed input and concurrency states.

The project must stay small, native, reproducible, and precise about assurance.
A fuzz campaign applies to one corpus, duration, compiler, sanitizer, kernel, and computer.
It is not proof that the implementation is secure.

## Decision

Phase 7 adds three assurance layers.

### JSON preflight

Run a SAX pass before DOM construction.
Reject invalid syntax, duplicate keys, excessive depth, and excessive token count.

Use these protocol limits:

- 64 nested containers
- 32,768 tokens

Use these runtime-policy limits:

- 32 nested containers
- 4,096 tokens

Keep the earlier byte limits.
Keep closed schema validation after the preflight.

### Shared fuzz invariants

Use one support library for these surfaces:

- protocol
- runtime policy
- log analysis
- ELF analysis
- supplied proc-text parsing

Check bounded responses, valid server output, exclusive result or error states, collection limits, metadata budgets, and preview limits.

Use the same support library in these configurations:

- deterministic GCC and Clang tests
- ASan and UBSan tests
- five optional Clang libFuzzer targets

Keep representative valid and invalid inputs in curated corpora.
Minimize each confirmed crash or hang.
Keep the minimized case as a regression input or named test.

### Concurrency and failure tests

Add a worker-factory seam for construction-failure tests.
When worker creation fails, stop and join each worker that already started.
Serialize shutdown ownership.
Test simultaneous shutdown, cancellation, deadlines, callback failures, and admission limits.
Run the focused scheduler tests with ThreadSanitizer.

## Native execution

Run the assurance workflow directly on Linux.
Do not require a container runtime.
This keeps host `openat2`, pidfd, procfs, thread, sanitizer, and filesystem behavior visible.

## CI policy

Run these jobs for pull requests and `main`:

- GCC Debug with warnings as errors
- Clang Release with warnings as errors
- Clang ASan and UBSan with leak detection
- deterministic fuzz smoke
- focused GCC ThreadSanitizer tests
- bounded Clang libFuzzer smoke

Keep longer campaigns as explicit scripts and a manual workflow.
Do not commit generated campaign artifacts.
Commit only a reviewed and minimized regression input.

## Consequences

The change gives these benefits:

- JSON ambiguity and depth bombs fail before DOM construction.
- Deterministic and coverage-guided tests share the same invariants.
- Rare scheduler construction and shutdown states are testable.
- Sanitizer and race-detector commands are reproducible.
- Each confirmed failure has a path to permanent coverage.

The change has these costs and limits:

- JSON is parsed two times.
- Duplicate-key tracking uses bounded memory for accepted keys.
- File-based fuzz targets are slower than pure in-memory parsers.
- Coverage depends on time and corpus selection.
- AddressSanitizer and ThreadSanitizer require separate builds.
- Cooperative cancellation cannot interrupt every blocking kernel call.

## Rejected alternatives

### Use libFuzzer only

Reject this option because normal GCC builds would lose adversarial smoke tests.
It would also make libFuzzer necessary for useful regression coverage.

### Use deterministic mutation only

Reject this option because it does not give coverage-guided exploration or libFuzzer minimization.

### Require a container test environment

Reject this option because it can hide the Linux host behavior that the project must test.
It does not solve a current requirement.

### Treat a clean sanitizer run as proof of security

Reject this claim.
A sanitizer detects selected failures on executed paths only.
Record the exact tool, version, command, duration, and limitation.
