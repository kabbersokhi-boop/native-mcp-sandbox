# ADR 0002: Local standard-I/O transport

- Status: Accepted
- Date: 2026-07-18

## Context

MCP can be transported in different ways. The initial use case is a local client
launching a local analysis process. A network listener would add authentication,
port exposure, lifecycle, and deployment concerns unrelated to the first use case.

## Decision

The first server transport will use JSON-RPC-compatible MCP messages over standard
input and standard output. Standard output will be owned by one response writer.
All diagnostics will go to standard error. No listening network socket will be
opened.

## Consequences

Process lifecycle and local client configuration remain simple, and the initial
network attack surface is absent. Remote clients are out of scope. Concurrent work
must send completed responses through the single writer instead of writing directly
from worker threads.
