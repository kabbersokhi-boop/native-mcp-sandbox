# Security Policy

## Supported versions

The project is pre-1.0. Only the latest tagged release and the default branch receive
security fixes.

Phase 6 accepts local MCP traffic over stdio and may expose configured read-only log,
ELF, and aggregate process-memory tools. Protocol framing, lifecycle, filesystem
containment, process identity, bounded parsing, worker scheduling, cancellation,
deadlines, output serialization, and dependencies are in scope.

## Reporting a vulnerability

Do not publish a working exploit in a public issue. Use GitHub private vulnerability
reporting. If it is unavailable, open a public issue without exploit details and request
a private channel.

Include, where possible:

- affected version and commit;
- operating system, kernel, compiler, and sanitizer configuration;
- minimal reproduction steps;
- expected and observed behavior;
- security impact; and
- whether the issue is already public.

Responses are best-effort; this is an independent educational project, not a service
with an SLA.

## Security expectations for changes

Changes affecting protocol parsing, filesystem access, process observation,
concurrency, resource limits, or dependencies require:

- tests for permitted and rejected behavior;
- saturation, duplicate-ID, cancellation, deadline, EOF, and output-framing tests when
  scheduler behavior changes;
- a threat-model update when assumptions change;
- sanitizer-clean execution where applicable;
- bounded failure paths and non-echoing diagnostics;
- focused review of object lifetime, data races, lock ordering, coroutine destruction,
  identity, lifecycle, and cancellation races; and
- no expansion to raw process memory, unconfigured PIDs, mutation, shell access, or
  networking without a separate threat-model decision.

Do not commit credentials, local paths, build outputs, archives, or confidential
material.
