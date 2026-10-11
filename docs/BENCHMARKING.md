# Benchmarking

## Flagship runtime study

The longer study is separate from the original smoke campaign below:

```sh
cmake --preset release -DNMS_BUILD_BENCHMARKS=ON
cmake --build --preset release
python3 scripts/run_runtime_study.py --server build/release/native-mcp-sandbox --benchmark build/release/native_mcp_runtime_study --mode study --output build/runtime-study-full
```

Use `--mode smoke` for five samples; `study` retains 100 per measurement. Six geometrically
sized/pathological fixtures run in fixed order with warm caches. Components have three warmups;
stdio scenarios have one. Raw nanosecond arrays accompany descriptive medians and (only at
100 samples) p95. No p99, confidence interval, outlier removal or language ranking is claimed.

`study.json`, `study.md` and `latency.svg` record binaries, fixtures, compiler settings, CPU,
kernel and source fingerprints. A dirty source tree is explicitly distinguished from its base
commit. Component peak RSS uses post-exec `/proc/self/status` VmHWM, includes measurement
storage and the scheduler probe, and is not server-only RSS. FD enumeration includes its own
descriptor on both sides. The synthetic scheduler probe tests 16 admitted requests, rejection
of a seventeenth, cancellation and worker joining; it does not bound blocking filesystem calls.
Concurrent throughput includes startup. DOM-only parsing remains an unsafe measurement reference.

The [checked-in candidate study](../site/data/study.md) is machine-specific evidence. Re-run
on the target machine; CI smoke timings are informational rather than performance thresholds.

## Original smoke campaign

Configure benchmark targets separately from normal builds:

```sh
cmake -S . -B build/bench -DCMAKE_BUILD_TYPE=Release -DNMS_BUILD_BENCHMARKS=ON
cmake --build build/bench --target native_mcp_bench native-mcp-sandbox
python3 scripts/run_benchmarks.py --benchmark build/bench/native_mcp_bench --server build/bench/native-mcp-sandbox --fixtures benchmarks/fixtures
python3 scripts/render_benchmark_report.py --input build/benchmark-report.json
```

The smoke campaign uses seven component samples and five end-to-end samples. Each
uses a steady monotonic clock, bounded raw arrays, and fixed fixture inputs. Canonical
JSON has one final newline and is validated offline against the supplied schema before
an atomic replace.

Reports are observations for the recorded build and environment, not universal
rankings. Shared CI runner timings are informational. Retain all valid samples;
this harness never filters an unusually fast or slow value. A sample can only be
excluded for a recorded operational failure, and then no complete report is written.

The component harness measures JSON preflight, DOM parsing, runtime-policy parsing,
proc-text parsing, and, where strict `openat2` is available, streaming log and ELF
operations. The stdio harness completes lifecycle messages, correlates IDs, bounds
stdout/stderr, rejects strict-mode stderr, and kills and reaps timeout failures.
It also calls every existing tool only under the configured server alias.

The paired SAX-preflight-plus-DOM versus DOM-only comparison uses identical valid
input and parsed-result validation; it is measurement-only and makes no superiority
claim. Streaming/whole-buffer references are omitted until independent truncation
equivalence is reviewed. A reduced-control reference is unsafe as a deployment
recommendation and is never a server option. End-to-end results use
`nanoseconds_per_scenario`, not an average over heterogeneous messages.
