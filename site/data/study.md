# Native runtime study

Mode: study. Raw samples are in study.json.

Component measurements include strict file opens and analyzers, but exclude MCP serialization.
Stdio scenarios include process creation, protocol I/O and shutdown.

| Fixture | Size | No-match scan median | Tail median | Harness peak RSS |
| --- | ---: | ---: | ---: | ---: |
| dense-16384.log | 16384 B | 0.049 ms | 0.063 ms | 5.37 MiB |
| dense-262144.log | 262144 B | 0.852 ms | 0.931 ms | 5.44 MiB |
| dense-4194304.log | 4194304 B | 15.760 ms | 16.710 ms | 5.43 MiB |
| dense-16777216.log | 16777216 B | 61.136 ms | 67.692 ms | 5.38 MiB |
| long-line-4194304.log | 4194304 B | 14.935 ms | 11.328 ms | 5.39 MiB |
| sparse-4194304.log | 4194296 B | 18.049 ms | 19.013 ms | 5.41 MiB |

## Stdio scenarios

- cold-start-initialize: median 1.104 ms (100 retained samples).
- four-tool-investigation: median 1.672 ms (100 retained samples).
- sixteen-concurrent-scans: median 147.074 ms (100 retained samples).

## Interpretation

- Measurements describe this machine and these binaries, not a universal language ranking.
- Component peak RSS is the native measurement process, including result storage and scheduler probe; it is not server-only RSS.
- Descriptor counts include the descriptor used to enumerate /proc/self/fd. Before/after counts use the same method.
- Cancellation timing uses cooperative synthetic work. It does not bound arbitrary filesystem system calls.
- All valid samples are retained in execution order; no outlier filtering. Fixtures run in the listed order with warm caches.
- DOM-only is an unsafe measurement reference, never a deployable server option.
- No p99 claim. p95 appears only with at least 100 samples and is descriptive, without a confidence claim.
