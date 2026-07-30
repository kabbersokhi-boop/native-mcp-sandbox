# Phase 10.1 provider contracts

This module is an external-agent foundation. It is intentionally separate from
the C++ server and has no MCP client, provider SDK, credential loader, live
provider adapter, streaming, or shell/process authority. The deterministic
fake provider is test-harness code only.

## Boundaries

`contracts.py` owns project types, a closed tool-schema subset, and bounded JSON
parsing. `endpoint_policy.py` validates production HTTPS and explicit
loopback-only fake endpoints; `transport.py` repeats that authority check
immediately before opening a socket and accepts only numeric loopback
destinations. It never follows redirects and never sends authorization or
proxy-authorization headers. `errors.py` and `retry.py` keep failure
classification and retry eligibility separate. `redaction.py`,
`environment.py`, and `transcript.py` provide bounded local control
primitives.

Provider responses are exactly one final assistant message or one to four
structured tool proposals. Unknown fields, duplicate keys, malformed nested
objects, unsupported content, duplicate call IDs, and malformed argument JSON
fail closed. Tool names are matched exactly against the advertised definitions;
an empty advertisement authorizes no tool. No proposal is executed by this PR.

Advertised tool arguments use a project-owned closed subset: `type`,
`properties`, `required`, `items`, `enum`, bounded string lengths, bounded
numeric ranges, and `additionalProperties` absent or exactly `false`. Object
schemas are closed at every level, arrays validate every item, and unsupported
keywords, types, malformed required/property declarations, non-finite numbers,
and duplicate required names fail before a tool definition is used.

## Defaults and hard maximums

All values are validated by `Limits` and have a hard maximum. Values are bytes,
counts, milliseconds, or attempts as named below.

The enforcement model is consistent: immutable value objects enforce only hard
ceilings and basic type invariants; each parsing, serialization, transcript,
schema-validation, transport, retry, and environment operation receives and
enforces the caller-selected `Limits`. A configured value may be stricter or
more permissive than the default, but cannot exceed its hard maximum. Raw
transcript bytes are bounded before JSON decoding, and response/request/tool
definition/argument limits are checked before their corresponding operation or
socket write.

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
that every result is loopback. At the transport socket boundary, a forged
endpoint is independently rechecked for exact HTTP scheme, test-only authority,
numeric loopback address, valid port, bounded request path, and agreement
between its public URL and numeric destination. Redirects are always rejected,
their bodies and locations are not read into diagnostics, and are never
followed. After connection, the read timeout is explicitly
`min(read-inactivity timeout, remaining total timeout)` for response headers and
each body read.

Retry decisions are pure. Configuration, authentication/authorization,
endpoint/TLS/redirect policy, validation, malformed or oversized content, and
permanent HTTP failures are not retryable. 408, 429, selected connection
failures, and selected 5xx failures may retry only within attempt and total
budgets. `Retry-After` accepts bounded decimal seconds only.

Transcripts contain canonical, bounded control metadata and provenance enums.
Event, adapter, model, correlation, and proposal identity fields use strict
project-owned identifier syntax; metadata is an allowlisted bounded contract.
Malformed transcripts, duplicate keys, invalid UTF-8, wrong field types, bad
enums, excessive nesting/collections/proposals, and oversized input all become
bounded `ProviderError` failures with fixed details. Provider text is guidance
or unsupported provider output, never evidence.

Redaction replaces configured secrets, including overlapping occurrences, before
the final UTF-8 bound is selected. Sensitive diagnostic fields additionally
remove authorization/header text, unapproved absolute paths, and raw PID
assignments. Ordinary bounded numbers and relative paths are not redacted just
because they resemble a PID or path. Child environments reject NUL values,
invalid names, duplicate allowlist entries, provider/secret variables, and
proxy variables by default; proxy allowlisting is available only for an
explicitly non-provider child.
Child environments are constructed from a new explicit allowlist and reject
provider credentials, tokens, proxy credentials, live-provider settings, and
secret-disclosing debug variables.

The test suite is standard-library-only, offline, and registered as
`agent.phase_10_1` in normal CTest execution.
