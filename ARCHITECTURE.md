# Architecture

## Current boundary

Phase 5 exposes four narrow MCP tools only when the operator supplies a trusted runtime
policy at startup:

- `logs.search` — bounded literal matching in one approved regular file;
- `logs.tail` — bounded previews of final logical lines;
- `elf.inspect` — bounded structural inspection of one approved ELF file; and
- `proc.memory` — bounded aggregate memory counters for one named same-UID process.

With no policy configuration, the server remains host-isolated and advertises no tools.
Filesystem targets are selected by symbolic root and relative path. Processes are
selected by symbolic name; the MCP client never supplies a raw PID.

## Data path

1. Read one bounded JSON-RPC line from stdin.
2. Validate MCP lifecycle and the closed tool-call envelope.
3. Apply the per-process tool-call burst limiter.
4. Resolve a configured filesystem root or process alias.
5. Pin the target identity before observation.
6. Read only the bounded data required by the selected analyzer.
7. Produce compact structured evidence conforming to the advertised output schema.
8. Serialize one bounded response through the single stdout writer.

## Runtime policy versions

Schema version 1 remains accepted and configures only filesystem roots. Schema version 2
contains exact `roots` and `processes` arrays. Either array may be empty, but at least one
capability must be configured. Process entries contain only a symbolic name and either an
unsigned PID or the string `self`.

## Process identity boundary

At startup each configured process is restricted to the server's effective UID. The
server opens and retains an `O_PATH` descriptor for `/proc/<pid>`, records field 22
(`starttime`) from `/proc/<pid>/stat`, and obtains a pidfd on supported kernels. Before
and after every observation it verifies the recorded identity. The kernel documents that
an open `/proc/<pid>` descriptor does not become attached to a later process if the PID is
reused; operations on the old descriptor fail instead.

Strict mode requires pidfd support. An explicit `--allow-legacy-process-pinning` option
permits old-kernel testing with the pinned proc-directory descriptor plus start-time
revalidation. The fallback is disclosed on stderr and is not the default security mode.

## `proc.memory`

The tool reads only fixed pseudo-files beneath the pinned process directory:

- `status` for selected memory counters, state, thread count, and effective UID;
- `statm` for page-based virtual, resident, shared, text, and data-plus-stack totals; and
- `smaps_rollup`, when available, for aggregate RSS, PSS, sharing, anonymous, swap, and
  locked-memory counters.

It never reads `/proc/<pid>/mem`, `maps`, `smaps`, `pagemap`, `cmdline`, `environ`,
`fd`, or target memory contents. `smaps_rollup` is optional because Linux may omit it or
deny it under ptrace access controls. A bounded category is returned instead of falling
back to more invasive sources.

## Resource invariants

- Runtime configuration text is capped at 64 KiB.
- At most 16 filesystem roots and 16 process aliases are accepted.
- Process pseudo-file reads are capped independently: stat 8 KiB, status 64 KiB, statm
  4 KiB, and smaps_rollup 256 KiB.
- Page-count multiplication is overflow checked.
- Log scans remain capped at 16 MiB; ELF selected metadata remains capped at 1 MiB.
- Tool calls remain limited to 16 per one-second window.
- Protocol requests and responses remain capped at 1 MiB.
- Stdout has one logical writer and contains only complete protocol messages.

## Error model

Malformed MCP calls and unknown tool names are JSON-RPC errors. Expected policy,
permission, process-lifetime, parse, size, read, and rate-limit failures are MCP tool
execution errors with `isError`. Successful structured results conform to advertised
output schemas. Execution errors omit success-only `structuredContent`.

## Concurrency

Phase 5 remains synchronous. There is no worker pool, coroutine scheduling,
cancellation, queue backpressure, or hard operation deadline. Bounded input and output
limits constrain individual calls; Phase 6 introduces orchestration and cancellation.
