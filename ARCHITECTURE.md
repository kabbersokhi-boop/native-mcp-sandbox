# Architecture

## Current boundary

Phase 3 connects the reviewed filesystem policy gate to two narrow MCP tools. Host
access is available only when the operator supplies a policy configuration at startup.
Unconfigured mode still advertises an empty tool list.

## Data path

1. Read one bounded JSON-RPC line from stdin.
2. Validate the MCP lifecycle and closed tool-call envelope.
3. Apply the bounded per-process tool-call rate limiter.
4. Validate arguments and select a configured symbolic root.
5. Resolve the relative path through the descriptor-based policy.
6. Pin and revalidate a bounded regular-file descriptor.
7. Stream at most the captured read budget in 8 KiB chunks.
8. Produce bounded escaped previews and structured metadata.
9. Serialize at most one response through the single stdout writer.

## Components

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Stdio server | Frame JSON-RPC and enforce lifecycle | Write diagnostics to stdout |
| Tool dispatcher | Validate calls and rate-limit bursts | Accept undeclared tools or fields |
| Filesystem policy | Resolve named-root relative paths | Follow symlinks or return special files |
| Log analyzer | Literal search and bounded tail | Load the whole file or execute contents |
| Result serializer | Return compact MCP evidence | Exceed the response budget |

## Streaming search

`logs.search` uses a Knuth–Morris–Pratt failure table and carries matcher state between
read chunks. Memory use depends on query, chunk, preview, and match limits—not file
length. Only the first bounded matches are retained.

## Streaming tail

`logs.tail` scans forward while retaining a bounded deque of the requested final lines.
Each line preview is independently bounded. Reverse-seek optimization is deferred
until reproducible benchmarks justify the extra complexity.

## Resource invariants

- Files larger than 16 MiB are rejected by the synchronous analyzer.
- The analyzer reads no bytes added after the policy captured the file size.
- At most 50 matches or tail lines are returned.
- Preview source data is capped at 512 bytes per returned line.
- Tool calls are limited to a burst of 16 per one-second window.
- Protocol requests and responses remain capped at 1 MiB.
- stdout has one logical writer.

## Error model

Malformed MCP calls and unknown tool names are JSON-RPC errors. Expected policy,
argument, read, and rate-limit failures are MCP tool execution errors with `isError`.
Successful structured results conform to advertised output schemas. Execution errors
omit `structuredContent` because those schemas describe successful output.

## Concurrency

Phase 3 is synchronous. There is no worker pool, coroutine scheduling, cancellation,
or enforced operation deadline. The small file cap limits individual work, while the
burst limiter reduces rapid repeated calls. Full scheduling and backpressure remain a
later phase.
