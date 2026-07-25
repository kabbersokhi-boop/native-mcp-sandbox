# Phase 10 plan: provider-neutral bounded investigation agent

## Status

Planning only. No provider transport, credential handling, live model call, new MCP tool, or server authority is implemented by this document.

Phase 10 begins from released tag `v0.10.1` at commit `2e19b5b6a14f5fbe26c5b4094c1750c6c5205db1`.

## Goal

Build a separate, bounded agent process that can ask a hosted language model for investigation guidance and then use only the MCP tools advertised by the existing native server.

The agent must preserve the boundary established by ADR 0013:

- the C++ server remains stdio-only, network-free, and credential-free;
- hosted model access belongs to a separate client process;
- provider output is untrusted;
- normal CI and release evidence remain deterministic and offline;
- live provider access is optional, manual, synthetic, and non-gating.

## Non-goals

Phase 10 does not authorize:

- networking or credentials inside `native-mcp-sandbox`;
- shell execution;
- arbitrary filesystem paths or raw PIDs;
- process discovery or process control;
- model-defined MCP methods or tools;
- automatic execution of free-form model text;
- sending host evidence to a provider without explicit operator approval;
- a live hosted provider as a normal CI or release dependency;
- a fixed dependency on NVIDIA NIM or any single model.

## Architecture

The planned system has three independent boundaries.

### Native MCP server

The existing C++ executable remains unchanged in authority. It validates MCP lifecycle and closed tool schemas, enforces runtime policy, and exposes only the operator-approved tool surface.

### Agent orchestrator

A new external process owns the investigation loop. It:

1. starts or connects to the MCP server over stdio;
2. discovers and records the exact advertised tool surface;
3. sends a bounded, redacted prompt to a configured provider client;
4. validates each proposed tool call against a closed local schema and the advertised allowlist;
5. issues approved MCP requests with explicit request IDs and deadlines;
6. validates MCP responses before using them as later model context;
7. stops on a bounded turn, tool-call, byte, retry, or time budget;
8. emits a redacted transcript and deterministic execution summary.

### Provider client

The provider client uses a provider-neutral request and response contract. An OpenAI-compatible adapter may target NVIDIA NIM, but endpoint and model identifiers remain configuration rather than source-code assumptions.

The provider client owns HTTP, TLS, authentication, streaming assembly, response-size enforcement, deadlines, retries, and provider error classification. It never executes tools directly.

## Required contracts

Before implementation, the first code PR must define and test these contracts.

### Provider request

The local request object contains only:

- configured model identifier;
- bounded system and user messages;
- the exact advertised tool definitions;
- deterministic generation controls where supported;
- maximum output budget;
- request correlation identifier.

Unknown fields are rejected in deterministic fixtures.

### Provider response

The accepted response is one of:

- a final assistant message;
- one or more structured tool-call proposals;
- a classified provider failure.

Every tool call requires a non-empty call identifier, an exact advertised tool name, and arguments that pass the locally owned closed schema. Unknown fields, duplicate call identifiers, malformed argument JSON, mixed final-text/tool-call ambiguity, and unsupported content are rejected.

### Agent transcript

The transcript records stable control evidence, not raw secrets or unrestricted host data. It may include:

- schema version;
- provider adapter name without credentials;
- model identifier;
- deterministic request and tool-call identifiers;
- accepted and rejected action classes;
- retry and deadline outcomes;
- redacted byte counts and hashes;
- MCP method and symbolic resource aliases;
- final bounded outcome.

It must not include API keys, authorization headers, raw environment values, absolute host paths, raw PIDs, command lines, provider request dumps containing secrets, or unapproved evidence.

## Fixed budgets

Implementation must expose configuration with safe defaults and hard maximums. The first implementation PR must choose exact values and test each boundary for:

- total agent wall-clock duration;
- provider connect timeout;
- provider read timeout;
- provider total request timeout;
- provider attempts and retry backoff;
- provider request bytes;
- provider response bytes;
- stream fragment count;
- agent turns;
- proposed tool calls per turn;
- total tool calls;
- MCP request and response bytes;
- transcript bytes.

Retry policy must be idempotent and bounded. Authentication and validation failures are not retried. Rate limits and selected transient failures may be retried only when the total attempt and time budgets permit.

## Data-flow policy

Evidence sent to a hosted provider is denied by default.

The operator must select an explicit data-flow mode:

- `synthetic-only`: only committed or generated synthetic fixtures may leave the host;
- `redacted-summary`: only locally transformed, schema-validated summaries may leave the host;
- `approved-evidence`: specifically approved evidence fields may leave the host.

The initial implementation and every automated test use `synthetic-only`. A live smoke test must also use synthetic input.

## Delivery sequence

### PR 10.1: contracts and deterministic provider double

Implement:

- provider-neutral data types and error taxonomy;
- closed provider response and tool-call validation;
- deterministic local fake OpenAI-compatible HTTP service;
- bounded non-streaming transport abstraction;
- transcript redaction primitives;
- unit tests for all schemas, limits, and error mappings.

This PR must not add a live NVIDIA call or repository secret.

### PR 10.2: bounded MCP orchestration

Implement:

- MCP server process lifecycle management;
- exact `tools/list` allowlist capture;
- validated model proposal to MCP request conversion;
- request-ID and tool-call correlation;
- bounded multi-turn loop;
- cancellation and deadline propagation;
- deterministic end-to-end fake-provider scenarios.

### PR 10.3: adversarial assurance

Add tests for:

- malformed and duplicate-key JSON;
- unexpected fields and invalid types;
- invented methods and tools;
- raw paths and PIDs;
- malformed tool arguments;
- prompt injection and fabricated evidence;
- oversized request, response, stream, and transcript data;
- truncated and reordered stream fragments;
- connection loss and timeout at each phase;
- 401, 403, 404, 408, 429, and 5xx responses;
- retry exhaustion and cancellation;
- secret, header, exception, and transcript redaction;
- provider output attempting shell or authority expansion.

### PR 10.4: optional OpenAI-compatible/NIM adapter

Only after PRs 10.1-10.3 pass independent review:

- add a configurable OpenAI-compatible adapter;
- keep base URL and model configurable;
- load credentials only from an environment variable or secret store;
- keep live access disabled by default;
- add an opt-in manual synthetic smoke path;
- keep normal CI offline and deterministic.

## CI gates

Every implementation PR must pass:

- existing GCC Debug and Clang Release suites;
- existing sanitizers, TSan orchestration, and fuzz smoke;
- deterministic fake-provider unit and integration tests;
- no-network normal CI tests;
- secret-pattern and transcript-redaction tests;
- exact advertised-tool allowlist tests;
- bounded failure and timeout tests;
- two-run byte-identical deterministic reports where reports are committed.

A live provider result is observational only and cannot replace these gates.

## Review gates

A Phase 10 implementation PR is not ready to merge until an independent review confirms:

- no change to native server authority;
- no network or credential code linked into the native server;
- all provider output is treated as untrusted;
- every tool call is locally schema-validated and allowlisted;
- all loops, retries, reads, writes, and transcripts are bounded;
- secrets and unapproved evidence cannot enter logs or committed fixtures;
- deterministic tests cover every failure class introduced by the PR;
- live provider behavior is optional and non-gating.

## Release policy

Phase 10 should be released only after the deterministic agent, fake-provider suite, adversarial coverage, and optional adapter have each passed separate review. The release version is selected at release time and is not assigned by this planning document.
