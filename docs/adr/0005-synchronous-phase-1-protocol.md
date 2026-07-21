# ADR 0005: Synchronous Phase 1 protocol

- Status: Accepted
- Date: 2026-07-18

## Context

The roadmap requires workers, cancellation, backpressure, and C++20 coroutines.
Phase 1 has no long-running tool.
Early concurrency would add lifecycle and output-order risks without a Phase 1 benefit.

## Decision

Use one synchronous standard-I/O loop in Phase 1.
Use one logical reader and one logical writer.
Run framing, JSON parsing, lifecycle dispatch, and serialization on one thread.
Do not add queues, workers, cancellation, or deadlines in Phase 1.

## Consequences

Protocol output is deterministic.
Worker output cannot interleave because Phase 1 has no workers.
A valid but difficult JSON message can use the reader until parsing finishes.
The request byte limit is the primary Phase 1 denial-of-service control.
Later orchestration must keep the single-writer rule.
