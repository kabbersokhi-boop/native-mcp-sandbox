# ADR 0002: Local standard-I/O transport

- Status: Accepted
- Date: 2026-07-18

## Context

MCP supports different transports.
The first use case starts a local analysis process from a local client.
A network listener would add authentication, port exposure, lifecycle, and deployment work.
That work is not necessary for the first use case.

## Decision

Use JSON-RPC-compatible MCP messages on standard input and standard output.
Use one serialized writer for standard output.
Write diagnostics to standard error.
Do not open a listening network socket.

## Consequences

The process lifecycle stays simple.
The initial network attack surface is absent.
Remote clients are not in scope.
Worker threads must send responses through the serialized writer.
