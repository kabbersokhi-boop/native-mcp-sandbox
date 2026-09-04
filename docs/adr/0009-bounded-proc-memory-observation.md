# ADR 0009: Bounded proc memory observation

- Status: Accepted for bounded tool set
- Date: 2026-07-18

## Context

A local investigation can need aggregate process-memory data.
It does not need raw memory, process discovery, environments, or unrestricted procfs access.
A numeric PID can be reused.
Detailed mapping interfaces can expose sensitive paths and addresses.

## Decision

Add `proc.memory` and runtime-policy schema version 2.
The operator assigns a process name to a PID or to the server process.
The MCP client selects the process name only.

Require the same effective UID.
At startup, open and keep the process proc-directory descriptor.
Record the process start-time field.
Require a pidfd when the kernel supports strict mode.

Read bounded aggregate counters from these files only:

- `status`
- `statm`
- optional `smaps_rollup`

Do not read raw memory, maps, command lines, environments, or file descriptors.
Verify process identity before and after collection.

Permit old kernels only with `--allow-legacy-process-pinning`.
The legacy mode keeps the proc-directory descriptor and verifies start time.
It does not provide pidfd-backed lifetime pinning.

## Consequences

The tool gives memory-triage data with less sensitive detail than raw memory or maps.
Each target must be known when the server starts.
The tool returns an error when the process exits or changes identity.
The result reports when `smaps_rollup` is not available.
The tool does not use a more invasive fallback.
