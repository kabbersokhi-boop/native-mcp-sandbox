# ADR 0014: require a bounded provider-neutral agent contract

## Status

Proposed for Phase 10 planning.

## Context

ADR 0013 keeps hosted model access outside the native MCP server. Phase 10 needs a more specific contract for the external agent so implementation does not accidentally widen authority, make hosted services part of deterministic assurance, or allow model output to bypass local validation.

The native server already owns a narrow and tested security boundary. It accepts MCP over stdio, advertises a closed tool surface, and enforces operator policy for symbolic file and process resources. A hosted model introduces a separate set of risks: credentials, remote data transfer, provider-controlled output, prompt injection, rate limits, streaming fragmentation, retries, and nondeterministic availability.

An OpenAI-compatible provider such as NVIDIA NIM may be used by an adapter, but provider compatibility is not sufficient evidence that a proposed tool call is authorized or safe.

## Decision

Phase 10 will implement a separate provider-neutral agent process. The agent is the only component permitted to communicate with both a hosted provider and the MCP server.

The native C++ server will not gain HTTP, TLS, credentials, provider SDKs, model configuration, prompt construction, or model-response parsing.

The agent will separate four stages:

1. provider request construction;
2. provider transport and response assembly;
3. local validation and authorization of proposed actions;
4. MCP execution and evidence validation.

No stage may pass an unvalidated tool proposal directly to the next authority boundary.

## Provider-neutral interface

The implementation will expose a provider interface whose inputs and outputs are project-owned types rather than provider SDK objects.

The interface accepts a bounded request containing messages, advertised tool definitions, model configuration, generation limits, and a correlation identifier.

It returns either:

- a final message;
- structured tool-call proposals;
- a classified failure.

Provider adapters may map this contract to an OpenAI-compatible API, including NVIDIA NIM, but adapter-specific response fields are not exposed to orchestration code unless explicitly modeled and validated.

Endpoint and model identifiers are configuration. No provider or model is compiled into the native server or required by normal CI.

## Local authorization gate

A proposed tool call is executable only when all of these conditions hold:

- the response passed bounded JSON and structural validation;
- the tool name exactly matches a tool returned by the current MCP `tools/list` response;
- the tool definition matches the locally expected closed schema;
- the arguments pass the project-owned closed schema for that tool;
- the call contains no unknown fields;
- the call does not contain an absolute path, raw PID, shell fragment, invented MCP method, or unadvertised authority;
- the total turn, tool-call, byte, retry, and time budgets still permit execution;
- the configured data-flow policy permits any evidence that may later be sent to the provider.

Rejected calls are recorded as bounded redacted control events. They are never repaired by guessing missing authority-bearing fields.

## Evidence and provider data flow

The agent treats MCP responses as untrusted evidence until they pass the expected response schema.

Evidence is denied from provider prompts by default. The operator selects one explicit mode:

- synthetic fixtures only;
- approved redacted summaries;
- specifically approved evidence fields.

Automated tests and the initial implementation use synthetic fixtures only.

The agent must not send API keys, authorization headers, raw environment variables, absolute host paths, raw PIDs, command lines, or unapproved host evidence to the provider.

## Credentials

Credentials are loaded only by the external agent from an environment variable or secret store. They are never accepted as command-line values.

Credentials and authorization headers must not appear in:

- process arguments;
- standard output or standard error;
- logs;
- exceptions;
- test fixtures;
- transcripts;
- benchmark reports;
- crash artifacts;
- committed configuration.

Missing credentials disable live access without affecting deterministic tests.

## Bounded transport

Every provider adapter must enforce independent hard limits for:

- connection establishment;
- read inactivity;
- total request duration;
- request bytes;
- response bytes;
- stream fragments;
- retry attempts;
- backoff duration;
- redirect behavior;
- transcript bytes.

Authentication failures, malformed responses, local validation failures, and operator-policy failures are not retried.

Rate limits and selected transient server or connection failures may be retried only when the operation is safe to repeat and the total attempt and wall-clock budgets permit it.

## Failure taxonomy

The project-owned error taxonomy must distinguish at least:

- configuration error;
- credential unavailable;
- DNS or connection failure;
- TLS failure;
- connect timeout;
- read timeout;
- total timeout;
- authentication or authorization failure;
- model or endpoint not found;
- rate limited;
- transient provider failure;
- permanent provider failure;
- malformed or truncated response;
- oversized response;
- unsupported provider content;
- invalid tool proposal;
- retry exhausted;
- cancelled.

Provider response bodies and headers are untrusted and must be redacted before entering diagnostics.

## Streaming

Streaming is deferred until the non-streaming contract and deterministic tests are complete.

A future streaming implementation must bound fragment count and bytes, reject invalid event ordering, detect truncation, and assemble one response before any tool proposal reaches the local authorization gate. Partial tool arguments are never executed.

## Deterministic assurance

Normal CI uses a local deterministic provider double and no credentials or internet access.

Tests must cover:

- valid final responses and valid tool calls;
- malformed JSON and duplicate keys;
- missing, duplicate, and unknown fields;
- invalid and unadvertised tools;
- malformed tool arguments;
- raw paths, raw PIDs, shell text, and invented methods;
- prompt injection and fabricated evidence;
- 401, 403, 404, 408, 429, and representative 5xx responses;
- connection refusal, reset, timeout, and truncation;
- oversized requests, responses, fragments, and transcripts;
- retry eligibility, exhaustion, and cancellation;
- secret redaction in logs, exceptions, and transcripts;
- deterministic request correlation and byte-identical stable reports.

The fake provider is part of the test harness, not production authority. It must support scripted responses and failures without opening access beyond the local test process.

## Live provider smoke

A live smoke test may be added only after deterministic and adversarial coverage passes review.

It must be manually triggered, use a repository or local secret, operate on synthetic input, enforce the same production limits, redact all output, and remain non-gating. A successful live response is compatibility evidence only, not proof of correctness or availability.

## Consequences

The provider and model can change without changing the native server boundary.

The external agent becomes a new security boundary and requires its own threat-model section, deterministic tests, redaction tests, and release evidence.

Implementation complexity increases because transport, validation, authorization, orchestration, and transcript generation cannot be collapsed into one provider callback. This separation is intentional and reviewable.

Provider-specific convenience features may be omitted when they cannot be represented safely in the project-owned contract.

## Alternatives rejected

### Put the NIM client in the C++ server

Rejected because it introduces networking, credentials, provider parsing, and remote availability into the component that enforces local host authority.

### Trust provider tool-call validation

Rejected because provider output is untrusted and provider schemas do not establish local authorization or operator policy.

### Use live NIM calls in normal CI

Rejected because credentials, rate limits, model changes, network failures, and nondeterministic output cannot provide reproducible merge evidence.

### Execute free-form model instructions

Rejected because model text is not an authority-bearing command format and could bypass the existing symbolic-resource and closed-schema controls.
