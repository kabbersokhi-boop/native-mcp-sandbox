# Assurance and verification

Native MCP Sandbox is designed around a narrow claim: an MCP client can inspect a small, operator-approved set of Linux evidence without receiving a shell, arbitrary filesystem access, raw process memory, networking inside the native server, or general process authority.

This document explains how that claim is tested, what evidence is available, and what the evidence does **not** prove.

## Current implementation baseline

The completed Phase 10 implementation is on `main` at merge commit:

```text
6125964b03e76277f42df1d60c52933e7ce0e861
```

The reviewed Phase 10.4 head was:

```text
ee663aa0904862495ed75e7722b455117d6c3afc
```

Exact-head GitHub Actions run `31915393822` completed successfully across all five required jobs.

The latest tagged release remains `v0.10.1`. The Phase 10 agent and optional provider adapter are complete on `main` but have not been assigned a new release tag.

## What is covered

| Area | Evidence |
| --- | --- |
| Native protocol and lifecycle | Closed JSON-RPC schemas, duplicate-key rejection, bounded framing, lifecycle tests, process-level stdio integration |
| Filesystem containment | Strict `openat2` tests, traversal/symlink/magic-link/mount-crossing rejection, descriptor pinning |
| Process identity | Same-UID policy, proc-directory retention, start-time validation, strict pidfd tests |
| Scheduling and cancellation | Fixed worker pool, bounded unfinished work, duplicate-ID rejection, deadlines, cancellation, shutdown and race tests |
| Agent contracts | Closed provider-neutral request/response contracts, endpoint policy, redaction, failure taxonomy and retry rules |
| MCP orchestration | Exact tool-surface capture, closed argument validation, serial execution, stable action identity, replay rejection and at-most-once behavior |
| Provider adapter | Configurable OpenAI-compatible non-streaming adapter, verified HTTPS, bounded reads, redirect rejection, credential isolation and synthetic-only egress |
| Adversarial assurance | Malformed input, oversized data, correlation attacks, fabricated evidence, replay attempts, transcript tampering and secret sentinels |
| Memory and undefined behavior | AddressSanitizer, UndefinedBehaviorSanitizer and leak-enabled test runs |
| Concurrency | Focused ThreadSanitizer builds and scheduler stress tests |
| Fuzzing | Deterministic mutation runner and five Clang libFuzzer targets |
| Determinism | Repeated canonical output checks and committed golden demonstration reports |

## Latest Phase 10 validation snapshot

The final Phase 10.4 candidate completed:

- Phase 10.4 focused tests: **16**
- Phase 10.3 adversarial tests: **34**
- Phase 10.2 orchestration tests: **32**
- Phase 10.1 provider-contract tests: **25**
- Phase 10.1 security regressions: **10**
- CTest `dev`: **21/21**
- CTest `sanitizers`: **21/21**
- CTest `thread-sanitizer`: **21/21**
- deterministic fuzz smoke: **100,000 iterations**
- libFuzzer smoke: **2,000 runs each** for protocol, runtime policy, ELF, log and process parsing
- `git diff --check`: passed

These numbers describe one exact tested implementation. They are not a general proof that the project has no defect.

## Reproduce the normal test gate

### Native and integrated tests

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure
```

### Sanitizers

```bash
cmake --preset sanitizers
cmake --build --preset sanitizers
ASAN_OPTIONS=detect_leaks=1 ctest --preset sanitizers --output-on-failure
```

### ThreadSanitizer

```bash
cmake --preset thread-sanitizer
cmake --build --preset thread-sanitizer
TSAN_OPTIONS=halt_on_error=1 ctest --preset thread-sanitizer --output-on-failure
```

### Phase 10 focused suites

```bash
python3 tests/phase_10_4_tests.py
python3 tests/phase_10_3_tests.py
python3 tests/phase_10_2_tests.py
python3 tests/phase_10_1_security_regressions.py
python3 tests/phase_10_1_tests.py
```

## Reproduce the deterministic fuzz gate

```bash
cmake --preset sanitizers
cmake --build --preset sanitizers

ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
./build/sanitizers/native_mcp_fuzz_smoke \
  --iterations 100000 --seed 828927513140
```

For coverage-guided campaigns:

```bash
NMS_FUZZ_SECONDS=300 ./scripts/run_fuzz_campaign.sh
```

See [`docs/FUZZING.md`](FUZZING.md) for target-specific commands, corpus handling and finding triage.

## Extended assurance

The manual `Extended Assurance` workflow performs longer campaigns on Ubuntu 24.04. It includes repeated deterministic fuzzing, ThreadSanitizer repetitions, strict `openat2` and pidfd integration, AF_UNIX/FIFO policy checks and five long-running libFuzzer campaigns.

The recorded Phase 7 campaign executed **61,925,751** libFuzzer inputs without an observed crash, sanitizer report, timeout or crash artifact. That evidence applies only to the tested source head, platform and inputs.

## Evidence interpretation

A green test run means:

- the named checks passed for the exact tested source and environment;
- no failure was observed on the executed paths;
- the repository retains repeatable commands and fixtures for independent verification.

A green test run does **not** mean:

- all possible inputs were tested;
- the software is free from vulnerabilities;
- the hosted-provider path was validated against every OpenAI-compatible service;
- the project is a general-purpose incident-response or remote-administration framework;
- operator policy mistakes or a compromised kernel are neutralized.

## Public proof links

- [CI workflow](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/workflows/ci.yml)
- [Final Phase 10.4 exact-head run](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/runs/31915393822)
- [Phase 10.4 pull request](https://github.com/kabbersokhi-boop/native-mcp-sandbox/pull/20)
- [Architecture](../ARCHITECTURE.md)
- [Threat model](../THREAT_MODEL.md)
- [Security policy](../SECURITY.md)
- [Fuzzing guide](FUZZING.md)

## Reporting a finding

Please follow [`SECURITY.md`](../SECURITY.md). Do not publish working exploit details in a public issue.
