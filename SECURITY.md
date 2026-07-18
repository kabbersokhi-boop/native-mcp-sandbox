# Security Policy

## Supported versions

The project is pre-1.0. Only the most recent tagged release and the default branch
receive security fixes.

Phase 0 is a foundation release. It does not accept MCP traffic or inspect local
files. Security claims in roadmap documents describe intended behavior, not current
capabilities.

## Reporting a vulnerability

Please do not publish a working exploit in a public issue. Use GitHub's private
security-advisory reporting feature when it is enabled for this repository. If that
feature is unavailable, open a public issue containing no exploit details and ask
the maintainer for a private reporting channel.

Include, where possible:

- affected version and commit;
- operating system and compiler;
- minimal reproduction steps;
- expected and observed behavior;
- security impact; and
- whether the issue is already public.

The project will acknowledge complete reports, reproduce them when possible, and
publish remediation details after a fix is available. Response times are
best-effort; this is currently an independent educational project, not a commercial
service with an SLA.

## Security expectations for changes

Changes affecting protocol parsing, filesystem access, process observation,
concurrency, resource limits, or dependencies require:

- tests for both permitted and rejected behavior;
- an update to `THREAT_MODEL.md` when assumptions change;
- sanitizer-clean execution where applicable; and
- a focused review of failure and cancellation paths.
