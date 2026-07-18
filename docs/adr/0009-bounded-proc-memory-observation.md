# ADR 0009: Bounded `/proc` memory observation

## Status

Accepted for Phase 5.

## Context

A useful local investigation can need process memory pressure without granting an AI
agent arbitrary process discovery, raw memory access, environment access, or unrestricted
`/proc` browsing. Numeric PIDs can be reused, and detailed mapping interfaces may expose
sensitive paths or addresses.

## Decision

Phase 5 adds one tool, `proc.memory`, and a version-2 trusted runtime policy. The
operator assigns symbolic names to specific PIDs or to the server process. The MCP client
selects only the symbolic name.

Each target must share the server's effective UID. Startup opens and retains the process
`/proc` directory, records the process start-time field, and requires a pidfd on supported
kernels. Observation reads bounded aggregate counters from `status`, `statm`, and optional
`smaps_rollup`; it does not read memory, mappings, command lines, environments, or file
descriptors. Identity is revalidated before and after collection.

Old kernels may be used only with the explicit `--allow-legacy-process-pinning` flag.
That mode retains the proc-directory descriptor and validates start time but cannot claim
pidfd-backed lifetime pinning.

## Consequences

The tool is useful for memory triage while returning substantially less sensitive data
than raw maps or memory. Targets must be known when the server starts. A process that
exits or changes identity produces an error instead of silently following a reused PID.
`smaps_rollup` may be unavailable because of kernel configuration or ptrace policy; the
result reports that limitation without trying a more invasive fallback.
