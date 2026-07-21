# Native fuzzing and security regression tests

Fuzzing gives evidence for one tested configuration.
It does not prove that the implementation is secure.

For each campaign, record these items:

- commit
- compiler and version
- sanitizer and version
- kernel
- command
- duration
- seed corpus
- changed resource limits

## Test surfaces

The shared harness tests five boundaries:

1. JSON-RPC and MCP dispatch, including JSON preflight.
2. Runtime-policy schema version 1 and version 2.
3. Bounded ELF32 and ELF64 analysis.
4. Streaming log search and tail.
5. Pure parsing of supplied `stat`, `status`, `statm`, and `smaps_rollup` data.

The proc parser harness does not open `/proc`.
It does not discover a PID.
It does not add a server capability.

Strict `openat2` and pidfd behavior use integration tests.
They do not use byte fuzzing.

## Run a deterministic campaign

Configure and build the sanitizer preset:

```bash
cmake --preset sanitizers
cmake --build --preset sanitizers
```

Run the deterministic mutation test:

```bash
ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
./build/sanitizers/native_mcp_fuzz_smoke \
  --iterations 20000 --seed 828927513140
```

The runner uses a fixed xorshift mutation stream.
Before defect triage, reproduce the failure with the printed seed and iteration.

## Run coverage-guided campaigns

Use Clang with ASan, UBSan, and libFuzzer.
Run all targets with this command:

```bash
NMS_FUZZ_SECONDS=300 ./scripts/run_fuzz_campaign.sh
```

The script does these actions:

1. It configures the fuzz build.
2. It treats warnings as errors.
3. It builds with two jobs.
4. It copies each curated corpus.
5. It runs each target for the selected time.
6. It writes generated artifacts under `build/` by default.

Set `NMS_FUZZ_BUILD_DIR` to change the build directory.
Set `NMS_FUZZ_ARTIFACT_DIR` to change the artifact directory.

To run one protocol target, use these commands:

```bash
rm -rf build/fuzz-corpus/protocol
mkdir -p build/fuzz-corpus/protocol
cp -a fuzz/corpus/protocol/. build/fuzz-corpus/protocol/
./build/fuzz/native_mcp_fuzz_protocol build/fuzz-corpus/protocol \
  -max_total_time=300 \
  -max_len=1048576 \
  -timeout=10 \
  -rss_limit_mb=2048 \
  -dict=fuzz/dictionaries/json.dict \
  -artifact_prefix=build/fuzz-artifacts/protocol/
```

libFuzzer adds new units to the corpus directory.
Do not run a campaign directly in the committed corpus directory.

## Triage a finding

Do not commit an opaque crash file.
Use this procedure:

1. Keep the original artifact outside the source tree.
2. Run the target with the artifact as its only input.
3. Confirm the finding with the applicable sanitizer.
4. Minimize the artifact with `-minimize_crash=1` or `-merge=1`.
5. Identify the defect in the implementation, invariant, or harness.
6. Correct the defect without a weaker security boundary.
7. Add a named regression test when possible.
8. Add the minimized input to a corpus only when it gives new durable coverage.

Classify the finding correctly.
Use one of these classifications:

- crash
- sanitizer finding
- timeout
- out-of-memory event
- invariant failure
- environmental failure

A resource failure after you increase a documented fuzz limit is not automatically a server vulnerability.

## Run concurrency stress

Byte fuzzing does not prove thread safety.
Run the native stress script:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
```

The script runs these tests:

- leak-enabled ASan and UBSan tests
- an extended deterministic mutation campaign
- focused GCC ThreadSanitizer scheduler tests

AddressSanitizer and ThreadSanitizer use separate builds.
Do not combine them in one binary.

## Run Extended Assurance

`.github/workflows/extended-assurance.yml` is a manual release gate.
It requires Ubuntu 24.04 with strict `openat2` and pidfd support.

The workflow runs these jobs:

- two deterministic campaigns with 100,000 iterations each
- 50 ThreadSanitizer unit repetitions
- 25 ThreadSanitizer stress repetitions
- 50 real AF_UNIX and FIFO policy repetitions
- 20 configured standard-I/O integration repetitions
- five parallel libFuzzer campaigns of 600 seconds each

The workflow uploads logs and crash directories.
The workflow is manual because it uses substantial runner time.

## Phase 7 evidence

Extended Assurance run `29724493408` completed on Ubuntu 24.04.
It tested source head `df576168fd44561254736a60c45188333bd1bc50`.

The deterministic seeds completed 100,000 iterations each.
The libFuzzer targets completed these execution counts:

- protocol: 3,035,825
- runtime policy: 9,602,233
- ELF: 11,820,395
- log: 3,000,495
- process parser: 34,466,803

The total was 61,925,751 executions.
The recorded jobs found no crash, sanitizer finding, timeout, or crash artifact.
The ThreadSanitizer and strict integration jobs also completed without a report.

## Release gate

Before a release, verify these conditions:

- GCC Debug passes with warnings as errors.
- Clang Release passes with warnings as errors.
- ASan and UBSan pass with leak detection.
- Focused ThreadSanitizer tests pass.
- Each curated corpus replays successfully.
- Each coverage-guided target completes its campaign.
- Strict `openat2` and pidfd integration passes without compatibility flags.
- Each confirmed finding has a correction and a regression test.

A clean campaign means that the tested paths had no observed failure.
It does not mean that no defect exists.
