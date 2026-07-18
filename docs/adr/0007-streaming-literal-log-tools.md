# ADR 0007: Streaming literal log tools

- Status: Accepted
- Date: 2026-07-18

## Context

The first agent-reachable host tools must demonstrate useful analysis without turning
the server into a generic file reader or pulling concurrency and regex complexity into
the security boundary.

## Decision

Phase 3 exposes `logs.search` and `logs.tail` only when a trusted startup policy is
loaded. Both tools accept a symbolic root plus relative path and obtain their file only
through `FilesystemPolicy`.

Search is literal, returns the first occurrence per matching line, supports optional ASCII-only case folding, and uses streaming KMP. Tail
scans forward and retains a bounded deque. Files are limited to 16 MiB, chunks to 8
KiB, queries to 256 bytes, results to 50 lines, and previews to 512 source bytes. File
growth does not expand the captured read budget. Binary output is escaped. Tool calls
use a small per-process burst limiter.

## Consequences

The implementation is deterministic, testable, and memory-bounded. It is not a regex
engine, recursive search service, file watcher, or high-throughput log platform.
Synchronous scans still lack hard deadlines and cancellation; those require the later
orchestration phase.
