# Architecture

## Current boundary

Phase 6 preserves the four Phase 5 read-only tools and adds bounded execution
orchestration. Host access still exists only when the operator supplies a trusted
runtime policy:

- `logs.search` — bounded literal matching in one approved regular file;
- `logs.tail` — bounded previews of final logical lines;
- `elf.inspect` — bounded structural inspection of one approved ELF file; and
- `proc.memory` — bounded aggregate counters for one named same-UID process.

With no policy configuration the server advertises no tools. Phase 6 adds no new host
data source, filesystem mutation, process control, shell execution, or networking.

## Protocol and work path

1. The main thread reads one bounded JSON-RPC line from stdin.
2. It validates the MCP lifecycle and closed request envelope.
3. Immediate lifecycle, discovery, and protocol responses remain on the reader path.
4. A valid `tools/call` reserves one slot in the bounded outstanding-work set.
5. A small C++20 coroutine suspends and places its handle in pre-reserved queue storage.
6. One of two worker threads resumes the coroutine and runs the existing policy-gated tool.
7. The analyzer cooperatively checks cancellation and its steady-clock deadline.
8. A single mutex-protected writer emits a complete bounded response line.
9. `notifications/cancelled` requests stop for matching in-flight work and suppresses its
   normal response.

Tool responses may complete out of request order. JSON-RPC IDs preserve correlation.
Lifecycle state remains owned by the stdin reader thread; workers never mutate it.

## Bounded orchestration

The conservative resource budget fixes:

- 16 accepted but unfinished tool calls, including running work;
- two worker threads;
- a 30-second steady-clock deadline per accepted tool call;
- 1 MiB request and response limits; and
- 16 tool submissions per one-second rate-limit window.

When the outstanding-work limit is full, a new tool call receives a bounded
`server_busy` execution error. A duplicate in-flight JSON-RPC ID receives
`duplicate_request_id`. The server does not grow an unbounded queue and does not create
one thread per request.

The coroutine frame is used only to bridge request admission to a fixed worker pool.
Coroutine handles are stored in a vector whose capacity is reserved at scheduler
construction, avoiding queue allocation from the suspension callback.

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
size; Phase 6 does not claim arbitrary preemption.

MCP task execution remains forbidden. Phase 6 uses normal request cancellation and does
not implement the experimental tasks capability.

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
