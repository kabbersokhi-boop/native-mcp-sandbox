# Security Policy

## Supported versions

The project is pre-1.0. Only the most recent tagged release and the default branch
receive security fixes.

Phase 5 accepts local MCP traffic over stdio and may expose configured read-only log,
ELF, and process-memory tools. Filesystem containment, process identity, bounded parsing,
protocol framing, lifecycle, output schemas, resource limits, and dependencies are in
scope.

## Reporting a vulnerability

Do not publish a working exploit in a public issue. Use GitHub private vulnerability
reporting. If unavailable, open a public issue without exploit details and request a
private channel.

Include, where possible:

- affected version and commit;
- operating system, kernel, and compiler;
- minimal reproduction steps;
- expected and observed behavior;
- security impact; and
- whether the issue is already public.

Responses are best-effort; this is an independent educational project, not a service
with an SLA.

## Security expectations for changes

Changes affecting protocol parsing, filesystem access, process observation, concurrency,
resource limits, or dependencies require:

- tests for permitted and rejected behavior;
- a threat-model update when assumptions change;
- sanitizer-clean execution where applicable;
- bounded failure paths and non-echoing diagnostics;
- focused review of identity, lifecycle, output framing, and cancellation behavior; and
- no expansion from aggregate process counters to raw memory or unconfigured PIDs without
  a new threat-model decision.

Do not commit credentials, local paths, build outputs, or archives.
