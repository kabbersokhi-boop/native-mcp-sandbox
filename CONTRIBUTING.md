# Contributing

Thank you for helping improve Native MCP Sandbox.

## Before opening a change

For substantial protocol, dependency, tool, or sandbox changes, open an issue first
and describe the use case, trust-boundary impact, and simpler alternatives considered.

Keep pull requests focused. Do not combine formatting, dependency updates, and
behavior changes unless they are inseparable.

## Local verification

Run development, release, and sanitizer builds before requesting review:

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

Concurrency changes also require the focused ThreadSanitizer tests. Parser, analyzer, or
resource-boundary changes require deterministic fuzz smoke and an appropriate timed
libFuzzer campaign:

```bash
CXX=g++ cmake --preset thread-sanitizer
cmake --build --preset thread-sanitizer
TSAN_OPTIONS=halt_on_error=1 ctest --preset thread-sanitizer -R '^orchestration\.(unit|stress)$'

NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

Minimize any crash, hang, sanitizer finding, or race and commit it as a focused regression
case. Do not commit raw campaign output or an unreviewed crash directory. The presets and
scripts intentionally use two compilation jobs to remain usable on modest machines.

## Engineering rules

- Use C++20 and RAII for resource ownership.
- Prefer bounded data structures and streaming algorithms.
- Treat protocol input, duplicate JSON keys, nesting, paths, file contents, process IDs,
  fuzz corpora, and timing as untrusted.
- Keep stdout exclusively for protocol messages in server mode.
- Never add arbitrary shell execution as an MCP tool.
- Add tests for invalid inputs, denied operations, rare construction failures, and
  shutdown races, not only happy paths.
- Reuse shared fuzz invariants instead of creating target-specific safety claims.
- Document security assumptions and limitations precisely.
- Avoid dependencies without an architecture decision record.

## Commit and pull-request guidance

Use imperative, specific commit subjects such as:

```text
Validate resource budget upper bounds
```

Pull-request descriptions should state what changed, why it changed, how it was
tested, and what security or resource assumptions were affected.

