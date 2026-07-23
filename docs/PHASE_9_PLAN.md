# Phase 9 plan: reproducible benchmarks and reference comparison

Phase 9 will add reproducible performance measurements.
It will compare the implementation with defined reference paths.
It will not weaken a security control.
It will not claim universal performance superiority.

## Release target

- Candidate version: `0.10.0`
- Base release: `v0.9.0`
- Base commit: `44577903fcfbf3282a57113ca65d3291152202c6`

The release version is a candidate until implementation review is complete.

## Objectives

Phase 9 will provide these outcomes:

1. Repeatable component benchmarks for stable in-memory or committed inputs.
2. Repeatable end-to-end benchmarks for the real standard-I/O server.
3. Machine-readable benchmark output.
4. Human-readable reports with exact environment metadata.
5. Reference comparisons that have equivalent work and output semantics.
6. Evidence that performance work preserves security and resource limits.

## Security boundary

Phase 9 must preserve the existing host boundary.
It must not add an MCP tool.
It must not change an existing tool schema.
It must not increase host authority.

Benchmark code must not add these capabilities:

- shell execution
- networking
- arbitrary absolute paths
- recursive filesystem search
- filesystem mutation
- raw process memory
- raw PID input through MCP
- process discovery
- process control
- dynamic worker scaling
- an automatic fallback from strict `openat2`
- an automatic fallback from strict pidfd pinning

A benchmark must not disable validation or a security control in the measured production path.
A reduced-control reference path can exist only inside benchmark code.
The report must label that path as measurement-only.
The reference path must not become a runtime option.

## Benchmark classes

Phase 9 will use two benchmark classes.

### Component benchmarks

Component benchmarks will measure one bounded operation.
They will use committed or generated deterministic inputs.
They will avoid unstable host state.

Candidate component surfaces are:

1. JSON SAX preflight for valid and rejected protocol inputs.
2. Protocol DOM parsing and closed-schema validation.
3. Runtime-policy parsing.
4. Literal log search for fixed file sizes and match positions.
5. Log tail for fixed file sizes and line lengths.
6. ELF inspection for committed minimal and representative fixtures.
7. Proc-text parsing from supplied fixture bytes.
8. Scheduler admission, completion, cancellation, and saturation.

The implementation review can remove a candidate surface.
It must record the reason.

### End-to-end benchmarks

End-to-end benchmarks will start the real `native-mcp-sandbox` executable.
They will use newline-delimited JSON-RPC over standard input and standard output.
They will complete the MCP lifecycle.
They will correlate responses by request ID.

Candidate scenarios are:

1. Unconfigured lifecycle and `tools/list`.
2. Configured lifecycle and `tools/list`.
3. One fixed call for each existing tool.
4. A bounded concurrent call set below the admission limit.
5. The deterministic Phase 8 investigation.

The end-to-end harness must bound process output.
It must use a monotonic deadline.
It must kill and reap the process after a timeout or byte-limit violation.
It must reject unexpected standard error in strict mode.

## Inputs and fixtures

Every benchmark input must be reproducible.
The repository will contain the input or the deterministic generator.

The fixture set must include these properties:

- fixed byte size
- fixed line count when applicable
- fixed match count when applicable
- fixed ELF structure when applicable
- fixed proc-text fields when applicable
- no private host data
- no runtime timestamps in canonical results
- no random seed without recording the seed

The implementation must not benchmark an arbitrary live process by default.
Proc parsing benchmarks must use supplied bytes.
An end-to-end `proc.memory` benchmark can use the configured server alias only.
Its report must not record raw memory counters as cross-machine performance evidence.

## Reference comparisons

Each reference comparison must state the question that it answers.
It must use equivalent input and output semantics.
It must not compare unrelated tools only because they have similar names.

Candidate reference paths are:

1. SAX preflight plus DOM parse compared with DOM parse alone.
2. Streaming literal log search compared with a bounded whole-buffer literal search.
3. Streaming log tail compared with a bounded whole-buffer tail implementation.
4. Direct component execution compared with the full MCP standard-I/O path.
5. One-worker scheduler execution compared with the production two-worker configuration.

A reference path must preserve the same result contract for the measured input.
Tests must verify semantic equivalence before timing begins.
A comparison must exclude an input class when the reference path cannot preserve the production result contract for that class.
The report must state each excluded input class.

The report must explain when a reference omits a production control.
It must not recommend that omission for deployment.

## Measurement method

The benchmark harness must use a steady monotonic clock.
It must separate setup from the timed operation when that separation is valid.
It must prevent the compiler from removing measured work.
It must validate the result outside or inside the timed region as declared by the case.

Each case must define these values:

- warm-up iterations or warm-up duration
- measured iterations or measured duration
- number of independent samples
- input size
- operation count
- concurrency level
- timeout
- random seed when applicable

The canonical summary must include at least these statistics:

- sample count
- median
- minimum
- maximum
- arithmetic mean
- standard deviation
- a documented percentile or confidence interval

### Outlier policy

The benchmark specification must define the outlier policy before a measured campaign starts.
The default policy must retain every valid timing sample.
A harness must not remove a sample only because it is slower or faster than the other samples.

A sample can be excluded only when a recorded operational condition invalidates the measurement.
Examples include a harness timeout, a failed semantic check, an interrupted process, or a declared system event that makes the sample incomplete.

A report that excludes a sample must include these values:

- the original sample count
- the retained sample count
- the excluded sample count
- one reason for each exclusion class
- summary statistics for the retained samples
- access to the bounded raw sample set when the report retains raw samples

The report must state when no sample was excluded.
The implementation must not apply an undocumented automatic outlier filter.

The plan does not select a benchmark framework.
Implementation review must compare a small project-owned harness with an established C++ benchmark library.
The selected option must support machine-readable output and offline builds.
The decision must be recorded in an ADR or in the Phase 9 manifest.

## Environment metadata

Every saved benchmark report must identify its environment.
The machine-readable output must include these values when available:

- repository commit
- dirty-worktree status
- benchmark executable hash
- compiler name and version
- compile and link flags
- build type
- CMake version
- CMake preset and relevant cache options
- benchmark framework name and version
- relevant dependency versions
- operating-system name and version
- kernel version
- CPU model
- logical CPU count
- CPU affinity
- CPU frequency-scaling governor
- turbo or boost state
- virtualization or container status
- page size
- monotonic clock name and reported resolution
- benchmark harness version
- benchmark schema version
- fixture-set version
- command-line arguments

The report must distinguish missing metadata from an empty value.
It must not contain secrets, user names, home-directory paths, or unrelated environment variables.

A measured campaign must state which noise controls were used.
Examples include CPU affinity, a performance governor, a fixed turbo policy, and an idle-system check.
The report must state when a control is unavailable or was not applied.
A comparison must not claim a stable small difference when required noise controls are absent.

## Output and reproducibility

The benchmark harness must write canonical JSON.
A report generator can produce Markdown from that JSON.

Canonical output requirements are:

- one documented JSON schema
- stable case identifiers
- stable unit names
- sorted object keys when canonical files are committed
- no unbounded arrays
- no raw temporary paths
- no wall-clock timestamp in golden output
- one final newline

Raw timing values are machine-dependent.
They must not be committed as universal golden results.
Tests must use structural invariants and bounded synthetic timing data.

A local run must be reproducible from one documented command.
The command must create reports under `build/` by default.
Generated performance reports must not enter the source tree without explicit review.

## CI policy

Shared GitHub-hosted runners are not stable performance laboratories.
Normal CI will verify benchmark correctness and reproducibility.
It will not gate a merge on a small timing regression.

Normal CI must verify these items:

- benchmark targets compile with GCC and Clang
- benchmark smoke cases complete within fixed limits
- machine-readable output passes schema validation
- fixture generation is deterministic
- reference results are semantically equivalent
- output bounds and timeouts work
- the existing five CI jobs still pass
- existing security and integration tests still pass

A separate manual workflow can collect informational timing evidence.
That workflow must record runner metadata.
Its results must be labelled as observations from that runner only.

A performance regression threshold can become a release gate only when the project has controlled hardware or a sufficiently stable baseline process.
That change requires a separate reviewed decision.

## Resource limits

Benchmark work must remain bounded.
The implementation plan must define limits for these resources:

- fixture bytes
- benchmark output bytes
- report bytes
- warm-up time
- measured time
- sample count
- subprocess lifetime
- unfinished end-to-end calls
- retained raw samples

The harness must fail closed after a limit violation.
It must not continue with a partial result that appears complete.

## Planned files

The implementation can add these files or equivalent files after review:

- `benchmarks/` for C++ benchmark targets
- `benchmarks/fixtures/` for committed deterministic inputs
- `scripts/run_benchmarks.py` for orchestration and bounded report capture
- `scripts/render_benchmark_report.py` for Markdown generation
- `docs/BENCHMARKING.md` for operator instructions and interpretation limits
- a benchmark JSON schema
- benchmark smoke and invariant tests
- CMake benchmark options and targets
- an optional manual benchmark workflow
- `PHASE_9_MANIFEST.md`

Benchmark targets must be disabled in normal production builds unless implementation review approves another bounded arrangement.

## Implementation sequence

Implementation will use this sequence:

1. Select the benchmark framework and record the decision.
2. Define case identifiers, units, and the JSON schema.
3. Add deterministic fixtures and fixture-invariant tests.
4. Add component benchmarks.
5. Add reference paths and semantic-equivalence tests.
6. Add the bounded end-to-end harness.
7. Add report generation and metadata capture.
8. Add CI smoke verification.
9. Run local release-build measurements on a recorded environment.
10. Audit all claims against the recorded evidence.

Implementation must remain in a draft PR until independent review is complete.

## Verification gates

Phase 9 is complete only when the final branch head passes these gates:

- GCC Debug build, CTest, and self-check
- Clang Release build, CTest, and self-check
- ASan and UBSan with leak detection
- focused ThreadSanitizer tests
- existing libFuzzer smoke tests
- benchmark target builds with the selected supported compilers
- deterministic fixture generation
- benchmark schema validation
- semantic-equivalence tests for each reference path
- bounded subprocess output and timeout tests
- benchmark smoke completion in CI
- independent security-boundary review
- independent review of statistical and comparison claims
- exact post-merge CI verification before tagging

A release report must identify the exact source commit and environment for each recorded measurement.

## Explicit exclusions

Phase 9 will not include these items:

- production optimization based only on one benchmark result
- removal of validation or security checks
- a new MCP tool
- a public benchmark service
- network benchmarking
- arbitrary host-process benchmarking
- cross-machine ranking without environment qualification
- a universal faster-than claim
- stable public API guarantees
- package distribution work
- release-hardening work assigned to Phase 10

## Non-claims

A benchmark result is an observation for one build, input set, and environment.
It is not proof of universal speed.
It is not proof of production readiness.
It is not proof of correctness or security.
It does not show that a reduced-control reference path is safe for deployment.
It does not justify a security-boundary change without separate review.
