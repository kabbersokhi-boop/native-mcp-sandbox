# Phase 10.1 provider contracts

This module is an external-agent foundation. It is intentionally separate from
the C++ server and has no MCP client, provider SDK, credential loader, live
provider adapter, streaming, or shell/process authority. The deterministic
fake provider is test-harness code only.

## Boundaries

`contracts.py` owns project types and closed JSON parsing. `endpoint_policy.py`
validates production HTTPS and explicit loopback-only fake endpoints.
`transport.py` exposes a non-streaming interface and implements only bounded
HTTP to a validated loopback fake endpoint. `errors.py` and `retry.py` keep
failure classification and retry eligibility separate. `redaction.py`,
`environment.py`, and `transcript.py` provide bounded local control primitives.

Provider responses are exactly one final assistant message or one to four
structured tool proposals. Unknown fields, duplicate keys, malformed nested
objects, unsupported content, duplicate call IDs, and malformed argument JSON
fail closed. Tool names are matched exactly against the advertised definitions;
no proposal is executed by this PR.

## Defaults and hard maximums

All values are validated by `Limits` and have a hard maximum. Values are bytes,
counts, milliseconds, or attempts as named below.

| Limit | Default | Hard maximum |
| --- | ---: | ---: |
| provider request bytes | 32 KiB | 256 KiB |
| provider response bytes | 64 KiB | 512 KiB |
| JSON nesting depth | 12 | 24 |
| object/array items | 32 | 128 |
| messages | 8 | 32 |
| message bytes | 8 KiB | 32 KiB |
| advertised tools | 8 | 32 |
| tool-definition bytes | 4 KiB | 16 KiB |
| proposed tool calls | 4 | 16 |
| tool-argument bytes | 4 KiB | 16 KiB |
| transcript bytes | 32 KiB | 128 KiB |
| connect timeout | 500 ms | 5 s |
| read-inactivity timeout | 1 s | 10 s |
| total request timeout | 5 s | 30 s |
| provider attempts | 3 | 5 |
| retry backoff | 50 ms | 500 ms |
| Retry-After | 1 s | 5 s |

The fake provider binds to a dynamically assigned `127.0.0.1` port and is
created and destroyed by each test context. Plain HTTP is accepted only after
the explicit test-only loopback opt-in and after injected resolution proves
that every result is loopback. Redirects are always rejected and are never
followed.

Retry decisions are pure. Configuration, authentication/authorization,
endpoint/TLS/redirect policy, validation, malformed or oversized content, and
permanent HTTP failures are not retryable. 408, 429, selected connection
failures, and selected 5xx failures may retry only within attempt and total
budgets. `Retry-After` accepts bounded decimal seconds only.

Transcripts contain canonical, bounded control metadata and provenance enums.
Provider text is guidance or unsupported provider output, never evidence.
Child environments are constructed from a new explicit allowlist and reject
provider credentials, tokens, proxy credentials, live-provider settings, and
secret-disclosing debug variables.

The test suite is standard-library-only, offline, and registered as
`agent.phase_10_1` in normal CTest execution.
