# ADR 0010: Bounded coroutine orchestration and cooperative cancellation

- Status: Accepted
- Date: 2026-07-18

## Context

Phases 3 through 5 ran tool calls on the standard-input reader thread.
This design prevented concurrent independent work, cancellation, and backpressure.
Concurrency can add unbounded memory, thread creation, output interleaving, lifetime defects, and data races.

## Decision

Use a fixed worker pool and a small C++20 coroutine adapter.

The work path is:

1. The reader validates a tool request.
2. The reader reserves one of 16 unfinished-work slots.
3. A coroutine suspends into reserved handle storage.
4. One of two workers resumes the coroutine.
5. The call uses a stop source and a steady-clock deadline.
6. The analyzer checks an immutable operation context.
7. A valid cancellation request requests stop and suppresses the response.
8. One serialized writer writes the complete response line.
9. Shutdown stops admission, drains accepted work, and joins workers.

Reject duplicate in-flight IDs.
Reject work above the unfinished-work limit.
Keep MCP task support forbidden.
Do not add a host capability in coroutine orchestration.

## Consequences

Independent calls can run at the same time.
Responses can finish out of order.
Memory and thread use stay bounded.
Cancellation is cooperative.
Deadline precision depends on analyzer checks and bounded system calls.
