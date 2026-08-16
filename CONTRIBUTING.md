# Contributing

Thank you for contributing to Native MCP Sandbox.

The project welcomes focused changes that preserve its narrow trust boundary, bounded behavior and reproducible assurance model.

## Start with the project boundary

Read these documents before proposing a security-sensitive change:

- [`README.md`](README.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`THREAT_MODEL.md`](THREAT_MODEL.md)
- [`SECURITY.md`](SECURITY.md)
- [`docs/ASSURANCE.md`](docs/ASSURANCE.md)

Open an issue before changing:

- the MCP protocol or lifecycle;
- a dependency;
- a native tool;
- a runtime-policy gate;
- the scheduler or concurrency model;
- provider networking or credentials;
- the data-flow policy;
- any architecture or authority boundary.

In the issue:

1. Describe the use case.
2. Identify each trust-boundary change.
3. Describe the alternatives considered.
4. Explain why a smaller change is insufficient.
5. Identify the tests and threat-model updates that will be required.

Keep pull requests focused. Do not combine unrelated formatting, dependency and behavioral changes.

## Engineering rules

- Use C++20 for native code and Python 3 for the external agent and deterministic tests.
- Use RAII for native resource ownership.
- Use bounded data structures and streaming reads for potentially large input.
- Treat protocol, runtime policy, files, procfs, provider responses, HTTP metadata, transcripts and timing as untrusted.
- Keep standard output reserved for complete protocol messages.
- Keep provider credentials outside the native server.
- Do not add a generic shell tool.
- Do not add arbitrary path or PID authority.
- Do not add native-server networking.
- Do not add parallel MCP execution without a separate threat-model decision.
- Add accepted and rejected-path tests.
- Add construction, cancellation, deadline and shutdown tests where applicable.
- Reuse the shared fuzz invariants.
- State security assumptions, residual risks and resource limits.
- Add an ADR before adding a dependency or changing an architecture boundary.

## Build and run the normal gate

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure

cmake --preset release
cmake --build --preset release
ctest --preset release --output-on-failure

cmake --preset sanitizers
cmake --build --preset sanitizers
ASAN_OPTIONS=detect_leaks=1 ctest --preset sanitizers --output-on-failure
```

## Run the Phase 10 suites

Changes to the external agent, provider contracts, orchestration, endpoint policy, redaction or transcript logic must run:

```bash
python3 tests/phase_10_4_tests.py
python3 tests/phase_10_3_tests.py
python3 tests/phase_10_2_tests.py
python3 tests/phase_10_1_security_regressions.py
python3 tests/phase_10_1_tests.py
```

Normal CI must remain offline and credential-free. Do not make a live provider result part of a merge gate.

## Run focused concurrency tests

For scheduler, cancellation, deadline or shutdown changes:

```bash
cmake --preset thread-sanitizer
cmake --build --preset thread-sanitizer
TSAN_OPTIONS=halt_on_error=1 \
  ctest --preset thread-sanitizer --output-on-failure
```

## Run stress and fuzz tests

For parser, analyzer, transport, resource-limit or security-boundary changes:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

Use longer campaigns when the risk requires it. Record the compiler, sanitizer, seed, duration and exact command.

See [`docs/FUZZING.md`](docs/FUZZING.md).

## Handle a test or fuzz finding

Do not commit an opaque crash file.

1. Keep the original artifact outside the source tree.
2. Reproduce the finding with one exact command.
3. Confirm it with the relevant sanitizer or race detector.
4. Minimize the input or scenario.
5. Identify the defect in the implementation, invariant or harness.
6. Correct the defect without weakening the security boundary.
7. Add a named regression test.
8. Add a corpus input only when it provides durable additional coverage.

Do not commit raw campaign output, unreviewed crash directories or secret-bearing captures.

## Documentation changes

Public documentation must:

- distinguish the tagged release from newer work on `main`;
- link claims to reproducible commands or evidence;
- state limitations and non-claims;
- avoid claiming universal correctness, security or provider compatibility;
- keep examples free of real credentials, private paths and host data;
- use relative repository links where possible.

Technical prose follows the project style in [`docs/WRITING_STYLE.md`](docs/WRITING_STYLE.md).

## Commit and pull-request text

Use an imperative, specific commit subject, for example:

```text
Validate provider response byte limits
```

The pull-request description should include:

- what changed;
- why it changed;
- how it was tested;
- which security assumptions changed;
- which resource limits changed;
- whether the native-server authority changed;
- whether normal CI remains offline and credential-free.

Complete the pull-request checklist and keep the exact-head test evidence current after every pushed correction.
