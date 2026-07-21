# Contributing

Thank you for your contribution to Native MCP Sandbox.

## Before you make a large change

Open an issue before you change one of these areas:

- the MCP protocol
- a dependency
- a tool
- a policy gate
- the security boundary
- the scheduler

In the issue, include this information:

1. Describe the use case.
2. Describe each change to the trust boundary.
3. Describe the alternatives that you considered.
4. Explain why a smaller change is not sufficient.

Keep each pull request focused.
Do not combine formatting, dependency, and behavior changes unless they cannot be separated.

## Run the normal tests

Run these commands before you request review:

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev

cmake --preset release
cmake --build --preset release
ctest --preset release

cmake --preset sanitizers
cmake --build --preset sanitizers
ASAN_OPTIONS=detect_leaks=1 ctest --preset sanitizers
```

## Run the focused tests

For a concurrency change, run the ThreadSanitizer tests:

```bash
CXX=g++ cmake --preset thread-sanitizer
cmake --build --preset thread-sanitizer
TSAN_OPTIONS=halt_on_error=1 \
  ctest --preset thread-sanitizer -R '^orchestration\.(unit|stress)$'
```

For a parser, analyzer, or resource-limit change, run these tests:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

Use a longer campaign when the risk requires it.
Record the compiler, sanitizer, seed, duration, and command.

## Handle a test finding

Do not commit an opaque crash file.
Use this procedure:

1. Keep the original artifact outside the source tree.
2. Reproduce the finding with one exact command.
3. Confirm the finding with the applicable sanitizer or race detector.
4. Minimize the input.
5. Identify the defect in the implementation, invariant, or harness.
6. Correct the defect without a weaker security boundary.
7. Add a named regression test when possible.
8. Add a corpus input only when it gives additional durable coverage.

Do not commit raw campaign output or an unreviewed crash directory.
The build presets use two jobs so that modest computers can run them.

## Engineering rules

- Use C++20.
- Use RAII for resource ownership.
- Use bounded data structures.
- Use streaming algorithms for large inputs.
- Treat all protocol input as untrusted.
- Treat runtime-policy JSON as untrusted before validation.
- Treat paths, file data, proc data, fuzz inputs, and timing as untrusted.
- Keep standard output for protocol messages only.
- Do not add a generic shell tool.
- Add tests for accepted and rejected inputs.
- Add tests for rare construction and shutdown failures.
- Reuse the shared fuzz invariants.
- State each security assumption and limitation.
- Add an ADR before you add a dependency or change an architecture boundary.

## Commit and pull-request text

Use an imperative and specific commit subject.
Example:

```text
Validate resource budget upper bounds
```

In the pull-request description, include this information:

- what you changed
- why you changed it
- how you tested it
- which security assumptions changed
- which resource limits changed
