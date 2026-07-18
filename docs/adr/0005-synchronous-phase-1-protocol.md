# ADR 0005: Synchronous Phase 1 protocol baseline

- Status: Accepted
- Date: 2026-07-18

## Context

The roadmap eventually needs bounded workers, cancellation, backpressure, and C++20
coroutines. Introducing them before any long-running tool exists would add lifecycle
and output-ordering failure modes without Phase 1 benefit.

## Decision

Phase 1 uses a synchronous stdio loop with one logical reader and writer. Bounded
framing, JSON parsing, lifecycle dispatch, and serialization run on the same thread.
Queues, cancellation, workers, and operation deadlines remain out of scope.

## Consequences

Protocol output is deterministic and cannot be interleaved by workers. A pathological
accepted JSON message can occupy the process until parsing completes, so the request
limit is the primary Phase 1 denial-of-service control. Later orchestration must
preserve the single-writer invariant and add deadlines and backpressure.
