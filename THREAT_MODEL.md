# Threat Model

## Assets

- confidentiality and integrity of host files and processes;
- privacy of command lines, environments, mappings, descriptors, and memory contents;
- integrity and framing of MCP stdout;
- bounded CPU, memory, descriptors, threads, queued work, JSON construction, and response
  size; and
- operator control over observable roots and processes.

## Trusted components

- the installed executable and trusted runtime policy file;
- the operating system, procfs implementation, C++ runtime, and compiler toolchain;
- the MCP host that launches the process; and
- operator-selected filesystem roots and process aliases.

Fuzz corpora, crash artifacts, inspected files, and all MCP client input are untrusted.

## Untrusted inputs

- every byte received through stdin;
- JSON syntax, nesting, token count, duplicate keys, methods, IDs, cancellation IDs, and
  tool arguments;
- runtime-policy JSON before schema validation;
- inspected log and ELF contents;
- changing procfs data and process lifetime;
- request timing, concurrency, bursts, cancellation races, and EOF timing; and
- host resource failures such as thread-creation or allocation failure.

## Controls

- no-argument mode exposes no host tools;
- bounded SAX JSON preflight before DOM construction;
- rejection of duplicate object keys;
- protocol limits of 64 nested containers and 32,768 tokens;
- runtime-policy limits of 32 containers and 4,096 tokens;
- closed configuration and tool schemas;
- strict filesystem containment and same-UID process pinning;
- fixed pseudo-files and bounded analyzers;
- a fixed two-thread worker pool instead of per-request threads;
- at most 16 unfinished tool calls;
- pre-reserved coroutine-handle queue storage;
- duplicate in-flight request-ID rejection with canonical non-negative numeric IDs;
- per-call steady-clock deadlines and cooperative stop tokens;
- MCP cancellation response suppression;
- exception-safe worker construction and serialized idempotent shutdown;
- one serialized protocol writer;
- no raw memory, mappings, command line, environment, or descriptor enumeration; and
- GCC, Clang, ASan, UBSan, leak detection, focused ThreadSanitizer, deterministic mutation,
  libFuzzer smoke, malformed-input, cancellation, saturation, lifecycle, and real-process
  tests.

## Adversarial assurance strategy

The deterministic fuzz runner and five libFuzzer targets share invariants for protocol,
runtime-policy, log, ELF, and pure bounded `/proc` text-parser paths. The proc harness accepts supplied bytes only and never opens host procfs. Fuzzed outputs must remain bounded; result/error
states must be exclusive; analyzer collections must respect configured limits; and server
responses must remain complete valid JSON-RPC objects.

Scheduler stress repeats concurrent admission, queued and running cancellation,
deadline/cancellation precedence, throwing completion callbacks, and simultaneous
shutdown. Thread-creation failure is injected after one worker has started to verify that
partial construction stops and joins the worker before propagating the failure.

Every confirmed crash, hang, sanitizer finding, or race should be minimized and retained
as a deterministic regression. Fuzzing duration and corpus size are finite, so a clean
campaign does not establish absence of defects.

## Residual risks and limitations

- Cancellation and deadlines are cooperative. They do not forcibly interrupt an
  arbitrary blocking system call or terminate a worker thread.
- A tool can exceed its deadline until its next explicit stop checkpoint. Existing reads
  are bounded, but Phase 7 does not claim hard real-time enforcement.
- The outstanding-work cap includes running and queued calls; it is process-wide rather
  than a per-client fairness policy.
- JSON preflight parses the input before the DOM parser and adds bounded CPU and memory
  overhead. It is not a replacement for schema validation.
- Duplicate-key tracking allocates memory proportional to accepted key tokens, within the
  byte and token caps.
- JSON-RPC responses can complete out of order, which clients must correlate by ID.
- Aggregate process counters remain non-atomic snapshots; some `statm` values are
  approximate and `smaps_rollup` can be unavailable.
- Sanitizers observe only executed paths and have their own blind spots. ASan/UBSan and
  ThreadSanitizer run in separate builds.
- Fuzz targets use temporary regular files and can encounter host descriptor or storage
  exhaustion; such environmental failures are not treated as parser defects.
- A privileged or compromised kernel can violate userspace assumptions.
- The legacy filesystem backend cannot detect every bind mount. The explicit legacy
  process mode lacks pidfd pinning.
- MCP tasks, durable job recovery, dynamic worker resizing, priorities, and distributed
  cancellation are not implemented.
