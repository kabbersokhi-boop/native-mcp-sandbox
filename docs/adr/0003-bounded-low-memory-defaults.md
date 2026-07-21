# ADR 0003: Bounded defaults for modest Linux computers

- Status: Accepted
- Date: 2026-07-18

## Context

The primary development computer has 8 GB of RAM.
Agent input and inspected files can be unexpectedly large.
Unrestricted concurrency can cause denial of service.

## Decision

Use bounded queues, fixed worker counts, byte limits, deadlines, and streaming analysis.
Use these initial defaults:

- two worker threads
- 16 unfinished calls
- 1 MiB request limit
- 1 MiB response limit
- 30-second operation deadline

Give each configurable value a hard upper limit.
Use two build jobs in the CMake presets.
Make large benchmarks and long fuzz campaigns optional.

## Consequences

The project can build and run on modest hardware.
The server rejects or truncates some workloads.
A result must report truncation so that a client does not treat partial evidence as complete evidence.
