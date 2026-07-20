# Architecture

## Current boundary

Phase 7 preserves the four Phase 6 read-only tools and the bounded two-worker execution
model. It adds parser preflight, native fuzz targets, sanitizer modes, and security
regressions without adding host authority. Host access still exists only when the
operator supplies a trusted runtime policy:

- `logs.search` — bounded literal matching in one approved regular file;
- `logs.tail` — bounded previews of final logical lines;
- `elf.inspect` — bounded structural inspection of one approved ELF file; and
- `proc.memory` — bounded aggregate counters for one named same-UID process.

With no policy configuration the server advertises no tools. Phase 7 adds no new host
data source, filesystem mutation, process control, shell execution, networking, or MCP
task execution.

## Protocol and work path

1. The main thread reads one byte-bounded JSON-RPC line from stdin.
2. A SAX preflight validates JSON syntax, duplicate keys, nesting depth, and token count
   before DOM construction.
3. The reader validates the MCP lifecycle and closed request envelope.
4. Immediate lifecycle, discovery, and protocol responses remain on the reader path.
5. A valid `tools/call` reserves one slot in the bounded outstanding-work set.
6. A small C++20 coroutine suspends and places its handle in pre-reserved queue storage.
7. One of two worker threads resumes the coroutine and runs the existing policy-gated tool.
8. The analyzer cooperatively checks cancellation and its steady-clock deadline.
9. A single mutex-protected writer emits a complete bounded response line.
10. `notifications/cancelled` requests stop for matching in-flight work and suppresses
    its normal response.

Tool responses may complete out of request order. JSON-RPC IDs preserve correlation.
Lifecycle state remains owned by the stdin reader thread; workers never mutate it.

## JSON safety gate

`preflight_json` uses nlohmann/json's SAX interface and does not construct a DOM. It
counts every scalar, container, and object key; tracks container depth; and stores object
keys only long enough to reject duplicates in the same object.

The protocol path permits:

- at most 64 nested arrays or objects; and
- at most 32,768 SAX tokens.

Runtime-policy parsing permits:

- at most 32 nested arrays or objects; and
- at most 4,096 tokens.

Existing 1 MiB protocol and 64 KiB configuration byte limits remain in force. Inputs that
pass preflight are parsed into the existing DOM and then validated against closed schemas.
The double parse trades bounded CPU for clearer resource and ambiguity controls.

## Bounded orchestration

The conservative resource budget fixes:

- 16 accepted but unfinished tool calls, including running work;
- two worker threads;
- a 30-second steady-clock deadline per accepted tool call;
- 1 MiB request and response limits; and
- 16 tool submissions per one-second rate-limit window.

When the outstanding-work limit is full, a new tool call receives a bounded
`server_busy` execution error. A duplicate in-flight JSON-RPC ID receives
`duplicate_request_id`. Equal signed and unsigned non-negative numeric IDs share one
canonical key. String IDs remain distinct from numbers. The server does not grow an
unbounded queue and does not create one thread per request.

The coroutine frame is used only to bridge request admission to a fixed worker pool.
Coroutine handles are stored in a vector whose capacity is reserved at scheduler
construction, avoiding queue allocation from the suspension callback.

Worker creation is exception safe. If a later thread cannot be created, the constructor
marks the partial pool as stopping, wakes and joins earlier workers, and then propagates
the exception. Shutdown has a separate serialization mutex, so simultaneous callers
cannot race while joining the same worker objects.

## Cancellation and deadlines

MCP `notifications/cancelled` is accepted only as a notification with a valid
`requestId`. Unknown or already-completed IDs are ignored. A matched cancellation:

- sets a `std::stop_source`;
- causes log, ELF, and proc analyzers to stop at explicit bounded checkpoints; and
- suppresses the normal tool response.

Deadlines use `std::chrono::steady_clock`. Expired work produces a bounded
`deadline_exceeded` tool error unless a client cancellation already suppressed the
response. Cancellation is cooperative, not forced thread termination. Blocking kernel
calls already used by the project remain individually bounded by file type and input
size; Phase 7 does not claim arbitrary preemption.

## Existing security gates

Filesystem tools still resolve symbolic roots through strict `openat2` by default and
accept only pinned bounded regular files. Process observation still accepts only
operator-defined aliases, enforces the server effective UID, retains `/proc/<pid>`, and
requires pidfd pinning in strict mode. Compatibility backends remain explicit opt-in and
retain their documented limitations.

## Shutdown and output

EOF drains already accepted work before joining workers. New submissions stop before
shutdown begins. Protocol writes are serialized under one mutex and contain complete
JSON-RPC lines only. Generic diagnostics use stderr and do not echo request, file, or
process contents.

## Assurance architecture

The `native_mcp_fuzz_support` library centralizes invariants for five surfaces:

- protocol and JSON safety;
- runtime-policy parsing;
- bounded ELF inspection; and
- streaming log search and tail; and
- pure parsing of bounded `stat`, `status`, `statm`, and `smaps_rollup` bytes.

A deterministic mutation executable invokes these invariants in ordinary CTest, which
keeps adversarial coverage available under GCC, Clang, and sanitizers. Optional Clang
libFuzzer entry points reuse exactly the same functions for coverage-guided exploration.
The process-parser surface accepts only supplied bytes and never opens host procfs.
Curated corpora and dictionaries live in `fuzz/`; generated crash artifacts live under
`build/` until they are minimized and deliberately promoted to regression inputs.

Concurrency regressions are separate from byte fuzzing. They repeat admission,
cancellation, deadline, exception, and simultaneous-shutdown scenarios and run in a
focused ThreadSanitizer build. The project uses native Linux execution; no container
runtime is part of the architecture.
