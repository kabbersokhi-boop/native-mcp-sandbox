# Benchmarking

Configure benchmark targets separately from normal builds:

```sh
cmake -S . -B build/bench -DCMAKE_BUILD_TYPE=Release -DNMS_BUILD_BENCHMARKS=ON
cmake --build build/bench --target native_mcp_bench native-mcp-sandbox
python3 scripts/run_benchmarks.py --benchmark build/bench/native_mcp_bench --server build/bench/native-mcp-sandbox --fixtures benchmarks/fixtures
python3 scripts/render_benchmark_report.py --input build/benchmark-report.json
```

The smoke campaign uses seven component samples and five end-to-end samples. Each
uses a steady monotonic clock, bounded raw arrays, and fixed fixture inputs. Canonical
JSON has one final newline and is validated structurally by the supplied schema.

Reports are observations for the recorded build and environment, not universal
rankings. Shared CI runner timings are informational. Retain all valid samples;
this harness never filters an unusually fast or slow value. A sample can only be
excluded for a recorded operational failure, and then no complete report is written.

The component harness measures JSON preflight, DOM parsing, runtime-policy parsing,
proc-text parsing, and, where strict `openat2` is available, streaming log and ELF
operations. The stdio harness completes lifecycle messages, correlates IDs, bounds
stdout/stderr, rejects strict-mode stderr, and kills and reaps timeout failures.
It also calls every existing tool only under the configured server alias.

The documented SAX/DOM and streaming/whole-buffer comparisons are measurement-only.
They must have equivalent input and result semantics before timing. A reduced-control
reference is unsafe as a deployment recommendation and is never a server option.
