# Security Policy

## Supported versions

The project is pre-1.0. Only the most recent tagged release and the default branch
receive security fixes.

Phase 2 adds a native filesystem policy library but does not expose filesystem access
through MCP. Protocol parsing, lifecycle, descriptor handling, path containment,
configuration validation, file-type enforcement, resource bounds, and dependency
issues are in scope.

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

Changes affecting protocol parsing, filesystem access, process observation,
concurrency, resource limits, or dependencies require:

- tests for permitted and rejected behavior;
- a threat-model update when assumptions change;
- sanitizer-clean execution where applicable;
- bounded failure paths and non-echoing diagnostics; and
- focused review of descriptor lifetime, path races, lifecycle, and output framing.

Do not commit credentials, local paths, builds, or archives.
