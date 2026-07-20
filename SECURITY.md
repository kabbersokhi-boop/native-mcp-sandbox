# Security Policy

## Supported versions

The project is pre-1.0. Only the latest tagged release and the default branch receive
security fixes.

Phase 7 accepts local MCP traffic over stdio and may expose configured read-only log,
ELF, and aggregate process-memory tools. Protocol framing, bounded JSON preflight,
lifecycle, filesystem containment, process identity, bounded parsing, worker scheduling,
cancellation, deadlines, output serialization, fuzz harnesses, and dependencies are in
scope.

## Reporting a vulnerability

Do not publish a working exploit in a public issue. Use GitHub private vulnerability
reporting. If it is unavailable, open a public issue without exploit details and request
a private channel.

Include, where possible:

- affected version and commit;
- operating system, kernel, compiler, and sanitizer configuration;
- minimal reproduction steps or a minimized fuzz artifact;
- exact fuzz target, seed, dictionary, flags, and campaign duration;
- expected and observed behavior;
- security impact; and
- whether the issue is already public.

Responses are best-effort; this is an independent educational project, not a service
with an SLA.

## Security expectations for changes

Changes affecting protocol parsing, filesystem access, process observation,
concurrency, resource limits, fuzz invariants, or dependencies require:

- tests for permitted and rejected behavior;
- duplicate-key, nesting, token-budget, and malformed-encoding regressions when JSON
  handling changes;
- saturation, duplicate-ID, cancellation, deadline, EOF, construction-failure,
  simultaneous-shutdown, and output-framing tests when scheduler behavior changes;
- a minimized permanent regression for every discovered crash, hang, sanitizer report,
  or data race;
- a threat-model update when assumptions change;
- sanitizer-clean execution where applicable;
- focused ThreadSanitizer execution for concurrency changes;
- bounded failure paths and non-echoing diagnostics;
- focused review of object lifetime, data races, lock ordering, coroutine destruction,
  identity, lifecycle, cancellation races, and exception cleanup; and
- no expansion to raw process memory, unconfigured PIDs, mutation, shell access, or
  networking without a separate threat-model decision.

The deterministic fuzz smoke test runs in ordinary CTest. Longer native campaigns use:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

A clean run is evidence for the exact build and executed paths, not a guarantee that no
vulnerability exists.

Do not commit credentials, local paths, build outputs, archives, raw crash dumps, or
confidential material. Commit a fuzz artifact only after minimization, review, and
placement as a deliberate corpus or regression input.
