# ADR 0005: Synchronous Protocol Loop

- Status: Accepted
- Date: 2026-07-18

## Context

The initial protocol has no long-running tool. Adding workers, cancellation, backpressure, and
C++20 coroutines before a tool needs them would increase lifecycle and output-order risk.

## Decision

Use one synchronous standard-I/O loop for the initial protocol.
Use one logical reader and one logical writer.
Run framing, JSON parsing, lifecycle dispatch, and serialization on one thread.
Do not add queues, workers, cancellation, or deadlines until a long-running tool requires them.

## Consequences

Protocol output is deterministic.
Worker output cannot interleave because the initial protocol has no workers.
A valid but difficult JSON message can use the reader until parsing finishes.
The request byte limit is the primary denial-of-service control.
Later orchestration must keep the single-writer rule.
