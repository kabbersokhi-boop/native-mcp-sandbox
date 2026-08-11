# Phase 10 plan: provider-neutral bounded investigation agent

## Status

Phase 10.2 implements the deterministic, offline stdio orchestration subset:
minimal child environment, initialize/tools-list capture, closed tool schemas,
serial at-most-once `tools/call` execution, bounded lifecycle, validated
evidence, and deterministic control transcript.  Live provider networking,
credentials, streaming, and final reporting remain outside this phase.

Planning only through PR #13. No provider transport, credential handling, live
model call, new MCP tool, or native-server authority is implemented by this
document. No Phase 10 release version is selected here.

Phase 10 begins from released tag `v0.10.1` at commit
`2e19b5b6a14f5fbe26c5b4094c1750c6c5205db1`.

## Goal

Build a separate, bounded agent process that can ask a hosted language model
for investigation guidance and then use only the MCP tools advertised by the
existing native server.

The agent must preserve the boundary established by ADR 0013:

- the C++ server remains stdio-only, network-free, and credential-free;
- hosted model access belongs to a separate client process;
- provider output is untrusted;
- normal CI and release evidence remain deterministic and offline;
- live provider access is optional, manual, synthetic, non-gating, and deferred
  until PRs 10.1–10.3 pass.

## Non-goals

Phase 10 does not authorize:

- networking or credentials inside `native-mcp-sandbox`;
- shell execution, arbitrary filesystem paths, raw PIDs, process discovery, or
  process control;
- model-defined MCP methods or tools;
- automatic execution of free-form model text;
- sending host evidence to a provider without explicit operator approval;
- a live hosted provider as a normal CI or release dependency;
- a fixed dependency on NVIDIA NIM or any single model;
- parallel MCP execution in PRs 10.1–10.3;
- streaming before the non-streaming implementation and tests are complete.

## Architecture

The planned system has three independent boundaries.

### Native MCP server

The existing C++ executable remains unchanged in authority. It validates MCP
lifecycle and closed tool schemas, enforces runtime policy, and exposes only
the operator-approved tool surface. It remains credential-free.

### Agent orchestrator

A new external process owns the investigation loop. It:

1. creates a deliberately scrubbed environment before starting the native
   server or any other child process;
2. starts or connects to the MCP server over stdio;
3. discovers and records the exact advertised tool surface;
4. sends a bounded, redacted prompt to a configured provider client;
5. validates every proposal against a closed local schema and the advertised
   allowlist;
6. issues approved MCP requests with explicit request IDs and deadlines;
7. validates MCP responses before using them as later model context;
8. stops on bounded turn, call, byte, retry, and time budgets; and
9. emits a redacted transcript and provenance-typed deterministic summary.

The child environment must use a minimal explicit allowlist. It must not copy
the parent environment and delete a few known keys. It must not contain
provider API keys, authorization tokens or headers, secret-store access tokens,
proxy credentials, live-provider configuration, or debugging variables that
could disclose secrets. Provider endpoint or model variables are excluded
unless explicitly allowlisted for a non-provider child. `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` are excluded unless explicitly
allowlisted for that child. The same scrubbed-environment rule applies to every
other child process.

### Provider client

The provider client uses a provider-neutral request and response contract. An
OpenAI-compatible adapter may target NVIDIA NIM, but endpoint and model
identifiers remain configurable rather than source-code assumptions.

The provider client owns HTTP, TLS, authentication, response-size enforcement,
deadlines, transport retries, and provider error classification. Streaming is
deferred until after the non-streaming implementation and deterministic tests.
The provider client never executes tools directly.

### Endpoint, redirect, and TLS policy

Production provider endpoints must use verified HTTPS. Before any request, the
adapter must validate the configured scheme and authority, reject URL user-info,
fragments, unsupported or ambiguous URL forms, and reject disabled certificate
verification. It must verify the server certificate and hostname.

Redirects are disabled by default. If a future explicitly configured redirect
mode is added, it must be bounded, must never forward credentials across
origins, must never downgrade HTTPS to HTTP, and must reject loopback,
link-local, private, multicast, or otherwise disallowed destinations from a
production endpoint.

The deterministic fake HTTP provider may use plain HTTP only when the test
explicitly opts into loopback HTTP, the destination resolves exclusively to
loopback, the listener binds only to loopback, and no live credential is loaded
or sent. The fake provider is test-harness authority only.

## Required contracts

Before implementation, the first code PR must define and test these contracts.

### Provider request and response

The local request object contains only:

- configured model identifier;
- bounded system and user messages;
- the exact advertised tool definitions;
- deterministic generation controls where supported;
- maximum output budget; and
- a stable provider-request correlation identifier.

Production request construction and production response parsing must reject
unknown fields, as must tool-call proposal parsing, transcript parsing, and
serialization where applicable. Deterministic fixtures and tests must exercise
the same closed schemas. Provider-specific metadata may be discarded only
inside an adapter after bounded parsing and only when the project-owned
contract explicitly permits it; it must never pass implicitly to the
orchestrator.

The accepted response is one of:

- a final assistant message;
- one or more structured tool-call proposals; or
- a classified provider failure.

Every proposal requires a non-empty call identifier, an exact advertised tool
name, and arguments that pass the locally owned closed schema. Unknown fields,
duplicate call identifiers, malformed argument JSON, mixed final-text/tool-call
ambiguity, and unsupported content are rejected.

### Environment and secret isolation

Credentials may be loaded only by the future external provider agent from an
environment variable or secret store. They are never command-line values and
are never available to the native server. The orchestrator must construct the
minimal allowlisted child environment before `exec` and must prove, with
deterministic sentinel tests, that secret values do not appear in child
environment, process arguments, stdout, stderr, exceptions, logs, transcripts,
reports, or crash artifacts.

### Action identity, retries, and replay

Provider retries are transport-level retries only. One stable local
provider-request correlation ID must identify all attempts. For each accepted
proposal, the orchestrator must derive one stable local action identity from
the validated action content and relevant execution context; a provider call ID
alone is not sufficient.

Completed and in-flight action identities must reject duplicate proposals
across provider attempts and agent turns. Each accepted action identity has
at-most-once MCP execution. A provider retry must never repeat an MCP action
that was already accepted or executed. Bounded retry state must survive
response ambiguity for the lifetime of the investigation.

The implementation and tests must distinguish:

- repeating an idempotent provider HTTP request before any tool execution;
- replaying a model proposal after transport ambiguity; and
- repeating an MCP tool call.

Only the first may be an automatic transport retry. The third must not happen
automatically; duplicate or ambiguous proposals are rejected or reported as a
bounded local failure.

### Multiple tool calls

The initial policy accepts multiple valid proposals and executes them serially
in provider-declared order, subject to per-turn and total-call budgets. PRs
10.1–10.3 must not execute MCP calls in parallel or reorder them. After the
first rejection, failure, cancellation, or timeout, processing of the
remaining calls in that provider response stops; later calls do not become
implicitly authorized. Parallel execution requires a separate threat-model and
concurrency decision.

### Evidence provenance and report schema

Provider text is guidance, never evidence. Every factual investigation claim in
the deterministic summary or report must trace to one of:

- a validated MCP response ID;
- a locally computed stable predicate derived from a validated MCP response;
- a committed synthetic fixture assertion; or
- a local control event such as timeout, rejection, or cancellation.

The report schema must distinguish provider suggestion, accepted tool proposal,
rejected proposal, validated MCP evidence, locally derived predicate, and final
supported conclusion. Provider-generated claims must not appear as established
facts, citations must not be fabricated, uncited model summaries must not be
released, provider text must not overwrite or reinterpret failed MCP evidence,
and provider text must not become a release assertion. Unsupported claims must
be omitted or explicitly classified as unsupported provider output.

## Fixed budgets and failure taxonomy

Implementation must expose configuration with safe defaults and hard maximums
for total agent wall-clock duration, provider connect/read/total timeouts,
attempts, backoff, request and response bytes, agent turns, calls per turn,
total calls, MCP request/response bytes, and transcript bytes.

The project-owned taxonomy must distinguish these classes:

- invalid provider configuration;
- credential unavailable;
- endpoint-policy rejection;
- insecure scheme;
- TLS verification failure;
- redirect rejected;
- DNS or selected connection failure;
- connect timeout;
- read timeout;
- total request timeout;
- invalid content type;
- request too large before transmission;
- HTTP 400 invalid request;
- HTTP 413 payload too large;
- HTTP 422 semantic request rejection;
- other permanent 4xx client-request failure;
- HTTP 401 authentication failure;
- HTTP 403 authorization failure;
- HTTP 404 endpoint or model not found;
- HTTP 408 request timeout;
- HTTP 429 rate limited;
- selected transient 5xx provider failure;
- other permanent or malformed provider failure;
- malformed JSON;
- duplicate-key JSON;
- truncated response;
- unsupported content;
- oversized response;
- invalid tool proposal;
- replay or duplicate proposal;
- retry exhausted; and
- cancelled.

Configuration, credential unavailable, endpoint policy, insecure scheme, TLS,
redirects, invalid
content, request-too-large, 400, 401, 403, 404, 413, 422, other permanent
4xx, malformed/duplicate/truncated/unsupported/oversized responses, invalid
proposals, replay, validation, authorization, and local-policy failures must
not be retried. 408, 429, selected connection failures, and selected 5xx
failures may be retried only while attempt and total wall-clock budgets allow.
The adapter must honor a valid bounded `Retry-After` value without exceeding
the remaining time budget. Raw response headers and bodies must never enter
diagnostics without bounded redaction.

The transcript records stable control evidence, not raw secrets or unrestricted
host data. It may include schema version, adapter name without credentials,
model identifier, deterministic request and action identifiers, proposal
classification, provenance references, retry/deadline outcomes, bounded byte
counts and hashes, MCP method and symbolic resource aliases, and the final
bounded outcome. It must not include API keys, authorization headers, raw
environment values, absolute host paths, raw PIDs, command lines, provider
request dumps containing secrets, or unapproved evidence.

## Data-flow policy

Evidence sent to a hosted provider is denied by default. The operator must
select one explicit mode:

- `synthetic-only`: only committed or generated synthetic fixtures may leave;
- `redacted-summary`: only locally transformed, schema-validated summaries may
  leave; or
- `approved-evidence`: specifically approved evidence fields may leave.

The initial implementation and every automated test use `synthetic-only`.

## Delivery sequence

### PR 10.1: contracts and deterministic provider double

Implement provider-neutral types, the complete error taxonomy, closed
production and fixture schemas, a bounded non-streaming transport abstraction,
the loopback-only fake HTTP provider, transcript redaction primitives, and
unit tests for limits, endpoint policy, redirects, TLS rejection, environment
scrubbing, and error mappings. The fake provider binds only to loopback and
has test-harness authority only.

### PR 10.2: bounded MCP orchestration

Implement process lifecycle with scrubbed child environments, exact
`tools/list` allowlist capture, validated proposal-to-MCP conversion, stable
request/action correlation, serial provider-order execution, at-most-once
deduplication, bounded multi-turn looping, and deterministic cancellation and
deadline behavior. No parallel MCP execution is authorized.

### PR 10.3: adversarial assurance

Add deterministic tests for malformed, duplicate-key, unknown-field, fabricated-
evidence, false-claim, missing-provenance, incorrect-response-correlation, and
nonexistent-request-ID citations; identical proposals on two provider attempts;
duplicate and content-identical call IDs; truncation; retries after execution;
later-turn duplicates; multiple-call stop behavior; all failure classes and
retry eligibility; secret sentinels across every output surface; endpoint and
redirect rejection; and oversized input/output.

### PR 10.4: optional OpenAI-compatible/NIM adapter

Only after PRs 10.1–10.3 pass independent review, add a configurable adapter,
keep endpoint and model configurable, load credentials only in the external
agent, keep live access disabled by default, and add an opt-in manual synthetic
smoke path. The live NIM smoke remains manual, synthetic, redacted,
non-gating, and deferred. Normal CI has no internet access or credential
requirement.

## CI and review gates

Every implementation PR must pass the existing GCC Debug, Clang Release,
sanitizer, TSan, fuzz-smoke, and integration suites plus deterministic
fake-provider tests, no-network tests, closed production-schema tests,
secret-pattern and redaction tests, endpoint and redirect policy tests,
allowlist tests, bounded failure/timeout tests, and byte-identical report
tests. A live provider result is observational only.

A Phase 10 implementation PR is not ready to merge until independent review
confirms no native-server authority change, no provider networking or
credentials in the server, local validation of every proposal, bounded loops
and transcripts, provenance for every factual claim, at-most-once execution,
and deterministic coverage for every introduced failure class.

## Release policy

Phase 10 should be released only after the deterministic agent, fake-provider
suite, adversarial coverage, and optional adapter have passed separate review.
No release version is selected by this planning PR.
