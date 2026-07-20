# ADR 0001: Security-first, read-only scope

- Status: Accepted
- Date: 2026-07-18

## Context

An MCP tool runtime receives arguments influenced by a probabilistic model and by
untrusted content. Arbitrary command execution would make a local demonstration easy
but would create a broad, poorly defined security boundary.

## Decision

The project will expose only named, schema-validated, read-only analysis tools. It
will not expose a generic shell, command runner, file writer, or binary executor.
Every new tool must document its permitted data sources, resource bounds, output
shape, cancellation behavior, and abuse cases.

## Consequences

The server will support fewer tasks than a general-purpose agent shell. Tool
implementations and tests will require more policy work. In return, the system will
have a smaller attack surface, clearer review criteria, and a defensible educational
story.

