# ADR 0014: require a bounded provider-neutral agent contract

## Status

Proposed for Phase 10 planning through PR #13.

## Context

ADR 0013 keeps hosted model access outside the native MCP server. Phase 10
needs a specific contract for the external agent so implementation does not
widen authority, make hosted services part of deterministic assurance, or allow
model output to bypass local validation.

The native server already owns a narrow security boundary. It accepts MCP over
stdio, advertises a closed tool surface, and enforces operator policy for
symbolic file and process resources. A hosted model adds risks from
credentials, remote data transfer, untrusted output, prompt injection, endpoint
configuration, TLS and redirects, retries, replay, streaming fragmentation,
and nondeterministic availability.

## Decision

Phase 10 will implement a separate provider-neutral agent process. The native
C++ server will not gain HTTP, TLS, credentials, provider SDKs, model
configuration, prompt construction, or model-response parsing. The native
server remains credential-free.

The agent separates provider request construction, provider transport and
response assembly, local validation and authorization, and MCP execution and
evidence validation. No unvalidated proposal may cross an authority boundary.

## Child-process environment

Before starting `native-mcp-sandbox` or any other child, the agent must create a
minimal deliberately scrubbed environment. It must not copy the parent
environment and delete known keys. The allowlist must exclude provider API
keys, authorization tokens or headers, secret-store access tokens, proxy
credentials, live-provider configuration, and debugging variables that can
disclose secrets. Provider endpoint/model variables are excluded unless
explicitly required for a non-provider child. `HTTP_PROXY`, `HTTPS_PROXY`,
`ALL_PROXY`, and `NO_PROXY` are excluded unless explicitly allowlisted for that
child.

Deterministic tests must use sentinel secret values and prove that none appear
in child environment, process arguments, stdout, stderr, exceptions, logs,
transcripts, reports, or crash artifacts. Credentials may exist only in the
external provider agent and never in the native server child.

## Provider-neutral interface and schemas

The provider interface uses project-owned bounded request and response types.
The request contains configured model, bounded messages, exact advertised tool
definitions, supported generation controls, output budget, and one stable
correlation identifier. Production provider-request construction,
provider-response parsing, tool-proposal parsing, transcript parsing, and
applicable serialization must reject unknown fields. Fixtures and tests must
exercise closed schemas too.

Provider-specific metadata may be discarded only inside an adapter after
bounded parsing when the project-owned contract explicitly permits it. It must
never pass implicitly into orchestration.

## Endpoint, redirect, and TLS policy

Production endpoints must use verified HTTPS. Before any request, the adapter
must validate scheme and authority, reject URL user-info and fragments, reject
unsupported or ambiguous URL forms, reject disabled certificate verification,
and verify the server certificate and hostname.

Redirects are disabled by default. Any future explicit redirect mode must be
bounded, must not forward credentials across origins, must not downgrade HTTPS
to HTTP, and must reject loopback, link-local, private, multicast, or otherwise
disallowed destinations from a production endpoint.

Plain HTTP is permitted only for the deterministic fake provider when the test
opts into loopback HTTP, the destination resolves exclusively to loopback, the
listener binds only to loopback, and no live credential is loaded or sent. The
fake provider is test-harness authority only.

## Local authorization and deterministic execution

A proposal is executable only after bounded JSON and structural validation,
exact advertised-tool matching, project-owned closed argument validation,
unknown-field rejection, authority checks, budget checks, and data-flow policy
checks. Rejected proposals are bounded redacted control events and are never
repaired by guessing.

Multiple valid proposals are accepted and executed serially in provider-declared
order, subject to per-turn and total-call budgets. PRs 10.1–10.3 must not
execute MCP calls in parallel or reorder them. After the first rejection,
failure, cancellation, or timeout, the remaining calls in that response stop
and do not become implicitly authorized. Parallel execution needs a separate
threat-model and concurrency decision.

Provider retries are transport-level retries only. One stable local provider
request ID spans all attempts. Each accepted proposal receives one stable
locally derived action identity from validated action content and execution
context. Completed and in-flight identities reject duplicates across attempts
and turns. MCP execution is at-most-once per accepted identity, and a retry
never repeats an accepted or executed action. Bounded state survives response
ambiguity for the investigation lifetime.

The contract distinguishes an idempotent provider HTTP retry before tool
execution, replay of a model proposal after transport ambiguity, and repeating
an MCP tool call. Only the first may be automatic; the third must never happen
automatically.

## Evidence provenance

Provider text is guidance, never evidence. Every factual claim in a
deterministic report must trace to a validated MCP response ID, a stable local
predicate derived from one, a committed synthetic fixture assertion, or a local
control event. The report distinguishes provider suggestion, accepted proposal,
rejected proposal, validated MCP evidence, locally derived predicate, and final
supported conclusion.

Provider claims must not become facts, fabricated citations, uncited summaries,
release assertions, or reinterpretations of failed MCP evidence. Unsupported
claims are omitted or explicitly classified as unsupported provider output.

## Credentials and data flow

Evidence is denied from provider prompts by default. The operator selects
`synthetic-only`, `redacted-summary`, or `approved-evidence`; automated tests
and the initial implementation use `synthetic-only`. The agent must not send
API keys, authorization headers, raw environments, absolute paths, raw PIDs,
command lines, or unapproved host evidence to a provider.

## Bounded transport and failure taxonomy

Adapters must independently bound connection, read inactivity, total duration,
request/response bytes, retries, backoff, redirects, and transcript bytes.
The taxonomy must distinguish invalid configuration, credential unavailable,
endpoint-policy rejection, insecure scheme, TLS verification failure, redirect
rejection, DNS or connection failure, connect timeout, read timeout, total
request timeout, invalid content type, request too large before transmission,
HTTP 400, 413, 422, other permanent 4xx, 401, 403, 404, 408, 429, selected
transient 5xx, other permanent/malformed failure, malformed JSON, duplicate-key
JSON, truncation, unsupported content, oversized response, invalid proposal,
replay/duplicate, retry exhaustion, and cancellation.

Configuration, credential unavailable, endpoint/TLS/redirect policy, invalid
content, request-too-large, 400, 401, 403, 404, 413, 422, permanent 4xx,
malformed response, validation, authorization, replay, and local-policy classes
are never retried. 408, 429, selected connection failures, and selected 5xx
may be retried only inside attempt and total wall-clock budgets. A valid bounded
`Retry-After` is honored only up to the remaining budget. Raw response headers
and bodies require bounded redaction before diagnostics.

## Streaming, fake provider, and live smoke

Streaming is deferred until non-streaming implementation and tests pass. A
future stream must bound fragments and bytes, reject invalid ordering, detect
truncation, and assemble a complete response before authorization; partial
arguments are never executed.

Normal CI has no internet or credential requirement. It uses a deterministic
fake provider that binds only to loopback and has test-harness authority only.
A live NIM smoke is manual, synthetic, redacted, non-gating, and deferred until
PRs 10.1–10.3 pass. Provider endpoint and model remain configurable.

## Deterministic assurance

Tests must cover closed production schemas and fixtures, endpoint/TLS/redirect
rejection, environment sentinels on every output surface, fabricated evidence,
false claims, missing or incorrect provenance, nonexistent request IDs,
duplicate proposals and call IDs, identical action content with different IDs,
truncation, retry after execution, later-turn duplicates, serial ordering,
stop-on-first-failure behavior, every failure class, retry eligibility,
redaction, cancellation, and byte-identical reports.

## Consequences

The provider and model can change without changing the native server boundary.
The external agent is a new security boundary and needs its own threat-model,
deterministic tests, redaction tests, and release evidence. Complexity remains
separated and reviewable. No Phase 10 release version is selected in this
planning PR.
