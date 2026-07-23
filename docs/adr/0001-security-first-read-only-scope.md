# ADR 0001: Security-first read-only scope

- Status: Accepted
- Date: 2026-07-18

## Context

An MCP tool receives arguments from a probabilistic model and from untrusted data.
A generic command tool would make the demonstration easy.
It would also make the security boundary large and unclear.

## Decision

Expose named, schema-validated, read-only analysis tools only.
Do not expose a generic shell, command runner, file writer, or binary executor.

For each new tool, document these items:

- permitted data sources
- resource limits
- output schema
- cancellation behavior
- abuse cases

## Consequences

The server supports fewer tasks than a general agent shell.
Each tool needs more policy work and more negative tests.
The smaller boundary gives clearer review rules and a smaller attack surface.
