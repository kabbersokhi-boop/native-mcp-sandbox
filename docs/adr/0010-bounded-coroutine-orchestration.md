# ADR 0010: Bounded coroutine orchestration and cooperative cancellation

- Status: Accepted
- Date: 2026-07-18

## Context

Phases 3 through 5 executed tool calls synchronously on the stdin reader. That kept the
initial security model simple but prevented concurrent independent work, request
cancellation, and queue backpressure. Adding concurrency can introduce unbounded memory,
thread creation, response interleaving, object-lifetime errors, and data races.

## Decision

Use a fixed-size worker pool and a small C++20 coroutine adapter:

- the reader validates a tool request and reserves one of 16 outstanding slots;
- a detached coroutine suspends onto pre-reserved handle storage;
- two persistent workers resume queued coroutine handles;
- each call owns a stop source and a steady-clock deadline;
- analyzers check an immutable operation context at bounded checkpoints;
- valid MCP cancellation requests stop matching work and suppress its response;
- one serialized writer emits complete response lines; and
- shutdown stops admission, drains accepted work, then joins workers.

Reject duplicate in-flight IDs and new work beyond the outstanding cap. Keep MCP task
support forbidden. Do not add new host capabilities in this phase.

## Consequences

Independent tool calls can complete concurrently and responses may arrive out of order.
Memory and thread use remain bounded. Cancellation is cooperative rather than forceful,
so deadline precision depends on analyzer checkpoints and bounded system calls. Later
stress and fuzzing work can target this deliberately small scheduling surface.
