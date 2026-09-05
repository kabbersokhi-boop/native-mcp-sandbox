# Assurance and verification

Native MCP Sandbox is designed around a narrow claim: an MCP client can inspect a small, operator-approved set of Linux evidence without receiving a shell, arbitrary filesystem access, raw process memory, networking inside the native server, or general process authority.

This document explains how that claim is tested, what evidence is available, and what the evidence does **not** prove.

## Current release evidence

Project version `v0.12.1` binds the C++ authority boundary and Python orchestration client to MCP
revision `2025-11-25`. It adds real-process interoperability coverage, bounded pagination, closed
output-schema enforcement, structured-evidence limits, and release artifacts with SBOMs,
checksums, and build-provenance attestations. The immutable release tag and GitHub Release identify
the exact source commit and validation context. Native-server validation is not, by itself, proof
of cross-language agent/server interoperability.

The earlier OpenAI-compatible adapter exact-head run, `31915393822`, completed successfully across all five required CI jobs before this release pass. It is useful historical evidence for that exact head, not a substitute for release-head validation.

## Claim → mechanism → evidence

| Claim | Mechanism | Evidence |
| --- | --- | --- |
| Native server has no networking surface | Stdio-only native architecture; provider adapter is external | [`ARCHITECTURE.md`](../ARCHITECTURE.md), [ADR 0013](adr/0013-external-model-client-boundary.md), source review of `src/` |
| Client cannot select raw file paths or PIDs | Operator policy maps aliases to roots and processes | [`tests/file_policy_tests.cpp`](../tests/file_policy_tests.cpp), [`tests/process_memory_tests.cpp`](../tests/process_memory_tests.cpp) |
| Strict file access is contained below a root | `openat2` resolve restrictions and retained descriptors | [`src/file_policy.cpp`](../src/file_policy.cpp), [`tests/security_regression_tests.cpp`](../tests/security_regression_tests.cpp) |
| Strict process identity is pinned | Same-UID checks, retained proc directory, start-time validation and pidfd | [`src/process_memory.cpp`](../src/process_memory.cpp), [`tests/process_memory_tests.cpp`](../tests/process_memory_tests.cpp) |
| Protocol parsing and work admission are bounded | Byte/token/depth limits, duplicate-key rejection and closed schemas | [`src/json_safety.cpp`](../src/json_safety.cpp), [`tests/protocol_tests.cpp`](../tests/protocol_tests.cpp), [`fuzz/`](../fuzz/) |
| Native scheduling is bounded | Fixed workers, unfinished-call cap, cancellation, deadlines and serialized output | [`src/orchestration.cpp`](../src/orchestration.cpp), [`tests/orchestration_stress_tests.cpp`](../tests/orchestration_stress_tests.cpp) |
| Provider cannot execute a tool directly | Captured surface and local schema/authorization validation construct MCP calls | [`tests/mcp_orchestration_tests.py`](../tests/mcp_orchestration_tests.py), [`docs/MCP_ORCHESTRATION.md`](MCP_ORCHESTRATION.md) |
| Duplicate proposals cannot repeat execution | Stable action identity and bounded replay state with serial execution | [`tests/adversarial_agent_tests.py`](../tests/adversarial_agent_tests.py), [`agent/native_mcp_agent/mcp_orchestrator.py`](../agent/native_mcp_agent/mcp_orchestrator.py) |
| Loopback fake transport is credential-free | Separate loopback-only test transport and child environment scrubbing | [`tests/openai_adapter_tests.py`](../tests/openai_adapter_tests.py), [`SECURITY.md`](../SECURITY.md) |
| Hosted egress is synthetic-only | Project-issued, non-transferable authorization bound to exact content | [`tests/openai_adapter_tests.py`](../tests/openai_adapter_tests.py), [`docs/OPENAI_COMPATIBLE_ADAPTER.md`](OPENAI_COMPATIBLE_ADAPTER.md) |

## Release validation snapshot

The release gate requires:

- OpenAI-compatible adapter tests: **16**
- adversarial agent tests: **34**
- bounded orchestration tests: **35**, including a real Python-client/C++-server contract check
- provider-contract tests: **25**
- provider security regressions: **10**
- CTest `dev`: **21/21**
- CTest `sanitizers`: **21/21**
- CTest `thread-sanitizer`: **21/21**
- deterministic fuzz smoke: **100,000 iterations**
- libFuzzer smoke: **2,000 runs each** for protocol, runtime policy, ELF, log and process parsing
- `git diff --check`: passed

These counts describe local release-candidate validation. Exact-head CI and clean-checkout
verification identify the current candidate source; its tag identifies the published release
source. These checks are evidence, not proof that the project has no defect.

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

### external agent focused suites

```bash
python3 tests/openai_adapter_tests.py
python3 tests/adversarial_agent_tests.py
python3 tests/mcp_orchestration_tests.py
python3 tests/provider_security_regression_tests.py
python3 tests/provider_contract_tests.py
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

## Historical assurance

The manual `Extended Assurance` workflow performs longer campaigns on Ubuntu 24.04. It includes repeated deterministic fuzzing, ThreadSanitizer repetitions, strict `openat2` and pidfd integration, AF_UNIX/FIFO policy checks and five long-running libFuzzer campaigns.

The recorded fuzzing campaign executed **61,925,751** libFuzzer inputs without an observed crash, sanitizer report, timeout or crash artifact. That historical number applies only to its recorded source head, platform and inputs; it is not carried forward as a result for `v0.12.1`.

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

- [Latest release](https://github.com/kabbersokhi-boop/native-mcp-sandbox/releases/latest) — assets, checksums, SBOMs, and provenance for the current tag.
- [CI workflow](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/workflows/ci.yml)
- [OpenAI-compatible adapter historical exact-head run](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/runs/31915393822)
- [OpenAI-compatible adapter pull request](https://github.com/kabbersokhi-boop/native-mcp-sandbox/pull/20)
- [Architecture](../ARCHITECTURE.md)
- [Threat model](../THREAT_MODEL.md)
- [Security policy](../SECURITY.md)
- [Fuzzing guide](FUZZING.md)

## Reporting a finding

Please follow [`SECURITY.md`](../SECURITY.md). Do not publish working exploit details in a public issue.
