# ADR 0003: Bounded defaults for modest Linux hosts

- Status: Accepted
- Date: 2026-07-18

## Context

The primary development machine has 8 GB of RAM. Agent inputs and inspected files
can be unexpectedly large, and unrestricted concurrency can turn valid requests into
denial of service.

## Decision

The server will use bounded queues, fixed worker counts, request and response byte
limits, deadlines, and streaming analysis. The initial defaults are two workers, a
16-item pending queue, 1 MiB request and response limits, and a 30-second operation
deadline. Configuration values will also have hard upper bounds.

Build presets use two jobs. Large benchmarks, extended fuzzing, and expensive
analysis datasets will be opt-in.

## Consequences

The project remains comfortable to build and demonstrate on modest hardware. Some
workloads will be rejected or truncated. Results must explicitly report truncation
so an agent does not mistake partial evidence for a complete scan.

