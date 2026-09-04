# ADR 0007: Streaming literal log tools

- Status: Accepted
- Date: 2026-07-18

## Context

The first host tools must give useful evidence.
They must not become a generic file reader.
They must not add regular-expression or concurrency complexity to the first tool boundary.

## Decision

Expose `logs.search` and `logs.tail` only when a trusted policy is loaded.
Each tool accepts a root name and a relative path.
Each tool obtains the file through `FilesystemPolicy`.

`logs.search` uses literal matching and streaming KMP.
It returns the first match in each matching line.
It can use ASCII-only case folding.

`logs.tail` scans forward and keeps a bounded deque.

Use these limits:

- 16 MiB file size
- 8 KiB read chunk
- 256-byte query
- 50 returned lines
- 512 source bytes for each preview

File growth must not increase the captured read budget.
Escape binary output.
Use a small process-wide burst limit.

## Consequences

The tools are deterministic and memory-bounded.
They are not a regular-expression engine, recursive search service, file watcher, or high-throughput log platform.
log tools does not provide cancellation or hard deadlines.
