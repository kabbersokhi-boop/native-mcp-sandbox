# Phase 10.3: deterministic adversarial assurance

Phase 10.3 is an offline adversarial assurance campaign for the closed Phase
10.1 provider contracts and Phase 10.2 stdio orchestration.  It adds no live
provider, credentials, native networking, tools, streaming, or parallel MCP
execution.

`tests/phase_10_3_tests.py` uses only committed fake-provider/MCP fixtures and
deterministic process seams.  Its named classes cover hostile provider parsing,
evidence forgery, correlation and replay, multi-call stop behavior, failure and
retry taxonomy, unique secret sentinels, endpoint/redirect/TLS policy,
transcript tampering and determinism, budgets/deadlines/lifecycle, tool-surface
and authorization attacks, serial authority, and native-source scope guards.

The campaign preserves the existing closed schemas, local provenance-only
evidence creation, one-active-call rule, deadline-dominated shutdown, scrubbed
child environment, redaction primitives, and credential-free normal CI.  It
does not claim that finite tests or fuzzing prove absence of all defects.
