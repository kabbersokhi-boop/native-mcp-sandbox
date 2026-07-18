# Security Policy

## Supported versions

The project is pre-1.0. Only the most recent tagged release and the default branch
receive security fixes.

Phase 1 accepts local MCP traffic over stdio but exposes no analysis tools and performs
no filesystem, process, shell, or network access. Protocol parsing, framing,
resource-bound, lifecycle, and dependency issues are in scope.

## Reporting a vulnerability

Do not publish a working exploit in a public issue. Use GitHub private vulnerability
reporting. If unavailable, open a public issue without exploit details and request a
private channel.

Include, where possible:

- affected version and commit;
- operating system and compiler;
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
- a threat-model update when assumptions change;
- sanitizer-clean execution where applicable;
- bounded failure paths and non-echoing diagnostics; and
- focused review of lifecycle, output framing, and cancellation behavior.

Do not commit credentials, local paths, builds, or archives.
