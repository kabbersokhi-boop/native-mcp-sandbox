# Native fuzzing and security-regression workflow

Phase 7 treats fuzzing as reproducible evidence, not a security proof. Record the exact
commit, compiler, sanitizer versions, kernel, command, duration, seed corpus, and any
resource-limit changes when reporting a campaign.

## Surfaces

The shared harnesses exercise five independent boundaries:

1. newline-delimited JSON-RPC and MCP dispatch, including bounded JSON preflight;
2. schema-v1 and schema-v2 runtime-policy parsing;
3. bounded ELF32/ELF64 structural inspection from an unlinked temporary regular file;
4. streaming log search and tail from an unlinked temporary regular file; and
5. pure parsing of supplied `stat`, `status`, `statm`, and `smaps_rollup` bytes.

The process-parser harness never opens `/proc`, discovers a PID, or broadens server
capabilities. Live pidfd and `openat2` behavior remains covered by strict integration
tests rather than byte fuzzing.

## Fast deterministic pass

The deterministic runner is available in every normal test build and uses a fixed
xorshift mutation stream:

```bash
cmake --preset sanitizers
cmake --build --preset sanitizers
ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
./build/sanitizers/native_mcp_fuzz_smoke \
  --iterations 20000 --seed 828927513140
```

A failure must be reproducible with the printed iteration count and seed before it is
triaged as a project defect.

## Coverage-guided campaigns

Clang and sanitizer instrumentation are mandatory for the optional libFuzzer targets:

```bash
NMS_FUZZ_SECONDS=300 ./scripts/run_fuzz_campaign.sh
```

The script first configures and builds with warnings as errors, ASan, UBSan, and
libFuzzer, then runs each curated corpus for the selected bounded duration. Override the
build and artifact locations with `NMS_FUZZ_BUILD_DIR` and
`NMS_FUZZ_ARTIFACT_DIR`. Generated artifacts remain under `build/` by default.

For one target, copy the curated seed corpus first because libFuzzer appends newly
discovered units to the corpus directory:

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

## Triage and minimization

Do not commit an opaque crash file. For each finding:

1. preserve the original artifact outside the source tree;
2. rerun the exact target with the artifact as its sole input;
3. confirm the finding under the relevant sanitizer;
4. minimize it with libFuzzer's `-minimize_crash=1` or `-merge=1` workflow;
5. determine whether the invariant, implementation, or harness is wrong;
6. fix the defect without weakening a security boundary;
7. add a named deterministic unit or integration regression when practical; and
8. add the minimized input to the appropriate corpus only when it provides durable
   coverage not already expressed by the named test.

A report should distinguish a crash, sanitizer finding, timeout, out-of-memory event,
asserted invariant, and environmental failure. Resource exhaustion caused only by
raising documented fuzz limits is not automatically a server vulnerability.

## Concurrency stress

Byte fuzzers do not establish thread safety. Run the dedicated native suite:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
```

It executes the full leak-enabled ASan/UBSan suite, an extended deterministic mutation
pass, and focused GCC ThreadSanitizer scheduler tests. ThreadSanitizer and
AddressSanitizer are separate builds because they cannot be combined reliably in one
binary.

## Release gate

A Phase 7 release candidate is not ready until:

- GCC Debug and Clang Release pass with warnings as errors;
- ASan/UBSan passes with leak detection enabled on a supported native Linux system;
- focused ThreadSanitizer tests complete without a report;
- every curated corpus replays successfully;
- bounded coverage-guided campaigns complete for all five targets;
- strict `openat2` and pidfd integration still passes without compatibility flags; and
- all discovered failures are either fixed and retained as regressions or explicitly
  documented as environmental and independently reproduced.

A clean campaign means only that no covered failure was observed under the recorded
conditions.
