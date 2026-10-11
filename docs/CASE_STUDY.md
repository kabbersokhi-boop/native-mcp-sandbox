# A native boundary for agent evidence

Source version: v0.13.0. Latest tagged release: v0.12.1.

## Problem and outcome

An agent investigating an incident needs useful evidence, not the authority to run arbitrary
commands. This C++20 server exposes four read-only MCP tools over stdio. Operators approve
root and process aliases; clients choose relative paths beneath those roots. The Python
orchestrator is an external client, not the native security boundary.

The [recorded investigation](../site/index.html) shows recovery, insufficient evidence, and
hostile proposals. It is a replay of synthetic runs against the real native executable, with
a deterministic scripted provider. It does not measure a live model's resistance to injection.
Run the actual installed pair with `native-mcp-agent demo --server /path/to/native-mcp-sandbox`.

## Why C++ belongs here

The meaningful distinction is ownership and enforcement, not the language label. RAII owns
descriptors and worker lifetimes. Linux `openat2` constrains file resolution; pidfds pin process
identity. Fixed admission bounds, cooperative cancellation, and serialized output constrain
resource use. Python handles integration and presentation without replacing these controls.

Follow the native code first: [file containment](../src/file_policy.cpp),
[bounded scheduling](../src/orchestration.cpp), [protocol dispatch](../src/server.cpp),
[stdio transport](../src/stdio_transport.cpp), and [process evidence](../src/process_memory.cpp).
The [architecture](../ARCHITECTURE.md) explains the existing design in detail.

## A reproduced defect, not a hypothetical claim

The baseline transport used blocking output. In supervised real-process regressions, four
stalled-peer cases exceeded a five-second harness deadline and closing stdout terminated the
process through SIGPIPE. Two positive cases passed. A client that stopped reading could keep
the server alive indefinitely in those tested paths.

The candidate uses nonblocking standard descriptors, a monotonic two-second write deadline,
and terminal connection failure after a partial write cannot finish. It never resumes a
damaged JSON stream. Failure wakes the input loop and requests cancellation; workers remain
owned and joined. All seven transport regressions pass after the change.
See the [decision and limitations](adr/0015-bounded-stdio-transport.md) and
[executable regression harness](../tests/transport_liveness_tests.py).

This is not a hard real-time shutdown guarantee: a filesystem syscall may block independently
of transport progress. Generic caller-supplied C++ streams also lack the native fd deadline.

## What the evidence establishes

- The hostile run distinguishes a native traversal denial from a Python invented-tool denial.
- Direct raw requests bypass Python and test native authorization and protocol errors.
- Forced unavailable kernel controls cause strict startup failure; compatibility requires an
  explicit operator flag and warning.
- The inconclusive report does not infer recovery from truncated search evidence. Changed log
  content changes the report; references connect conclusions to tool responses.
- A pinned independent official SDK exercises discovery, all four tools, correlation and errors.

The [generated evaluation](../site/data/evaluation.md) separates individual cases from named
regression suites. It is not a universal security score. Historical release fuzz totals remain
historical; they are not attributed to this uncommitted candidate.

## Measure the cost, including unfavorable results

The [runtime study](../site/data/study.md) retains raw samples and records fixture hashes,
compiler settings, CPU, kernel, binary hashes and source fingerprints. It measures six fixture
shapes, startup, a four-tool workflow, and bounded concurrent scans. It reports descriptor
stability, thread counts, admission rejection and cooperative cancellation. Follow the linked
artifact for numbers rather than treating one machine's results as a product guarantee.

Peak RSS comes from the native process's post-exec `/proc` high-water mark, not the Python
launcher's inherited `getrusage` value. That distinction was found and corrected during study
validation. The preflight-plus-DOM comparison measures the cost of an extra control against a
DOM-only reference; the reference is not a safe deployment mode. No cross-language speedup
or p99 claim is made. [Reproduction and methodology](BENCHMARKING.md).

## Limits and next decision

This is a capability-bounded evidence server, not a kernel/container sandbox. A compromised
native process retains OS privileges. Hostile bytes are data; report hashes detect changes
but do not authenticate a rewritten artifact. Hosted evidence feedback remains disabled in
the existing synthetic-only provider mode. No arbitrary execution or remediation is added.

The next optimization should follow a measured bottleneck, not a desire to add frameworks.
Independent users and production workloads have not yet validated usability or scale.
