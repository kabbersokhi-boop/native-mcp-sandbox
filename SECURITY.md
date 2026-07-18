# Security Policy

## Supported versions

The project is pre-1.0. Only the latest tagged release and the default branch receive
security fixes.

Phase 3 exposes read-only log tools only when an operator supplies a policy
configuration. Reports involving protocol framing, lifecycle, tool schemas, rate
limiting, path containment, descriptor identity, streaming limits, output sanitization,
dependencies, or information disclosure are in scope.

## Reporting a vulnerability

Use GitHub private vulnerability reporting. Do not publish a working exploit or
sensitive local evidence in a public issue. If private reporting is unavailable, open
a public issue without exploit details and request a private channel.

Include where possible:

- affected version and commit;
- Linux kernel, compiler, and configuration mode;
- minimal reproduction steps;
- expected and observed behavior;
- security impact;
- whether strict `openat2` or legacy mode was active.

Responses are best-effort; this is an independent educational project, not a service
with an SLA.

## Expectations for changes

Security-sensitive changes require permitted and denied tests, threat-model updates,
strict warnings, sanitizer-clean execution where applicable, bounded failures,
non-echoing diagnostics, and focused review of protocol output and host-access paths.
Do not commit credentials, local paths, builds, archives, or private material.
