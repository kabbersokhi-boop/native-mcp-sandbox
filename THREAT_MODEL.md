# Threat Model

## Assets

- confidentiality and integrity of host files and processes;
- privacy of command lines, environments, mappings, descriptors, and memory contents;
- integrity and framing of MCP stdout;
- bounded CPU, memory, descriptors, threads, queued work, and response size; and
- operator control over observable roots and processes.

## Trusted components

- the installed executable and trusted runtime policy file;
- the operating system, procfs implementation, C++ runtime, and compiler toolchain;
- the MCP host that launches the process; and
- operator-selected filesystem roots and process aliases.

## Untrusted inputs

- every byte received through stdin;
- JSON structure, methods, IDs, cancellation IDs, and tool arguments;
- inspected log and ELF contents;
- changing procfs data and process lifetime; and
- request timing, concurrency, bursts, cancellation races, and EOF timing.

## Controls

- no-argument mode exposes no host tools;
- closed configuration and tool schemas;
- strict filesystem containment and same-UID process pinning;
- fixed pseudo-files and bounded parsers;
- a fixed two-thread worker pool instead of per-request threads;
- at most 16 unfinished tool calls;
- pre-reserved coroutine-handle queue storage;
- duplicate in-flight request-ID rejection;
- per-call steady-clock deadlines and cooperative stop tokens;
- MCP cancellation response suppression;
- one serialized protocol writer;
- no raw memory, mappings, command line, environment, or descriptor enumeration; and
- GCC, Clang, ASan, UBSan, ThreadSanitizer orchestration checks, malformed-input,
  cancellation, saturation, lifecycle, and real-process tests.

## Residual risks and limitations

- Cancellation and deadlines are cooperative. They do not forcibly interrupt an
  arbitrary blocking system call or terminate a worker thread.
- A tool can exceed its deadline until its next explicit stop checkpoint. Existing reads
  are bounded, but Phase 6 does not claim hard real-time enforcement.
- The outstanding-work cap includes running and queued calls; it is process-wide rather
  than a per-client fairness policy.
- JSON-RPC responses can complete out of order, which clients must correlate by ID.
- Aggregate process counters remain non-atomic snapshots; some `statm` values are
  approximate and `smaps_rollup` can be unavailable.
- A privileged or compromised kernel can violate userspace assumptions.
- The legacy filesystem backend cannot detect every bind mount. The explicit legacy
  process mode lacks pidfd pinning.
- MCP tasks, durable job recovery, dynamic worker resizing, priorities, and distributed
  cancellation are not implemented.
