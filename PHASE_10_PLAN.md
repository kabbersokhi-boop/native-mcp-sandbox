# Phase 10 plan and implementation record

## Status

Phase 10 is complete on `main`.

| Increment | Scope | Status |
| --- | --- | --- |
| 10.1 | Provider-neutral contracts and deterministic provider double | Complete — PR #14 |
| 10.2 | Bounded serial MCP orchestration | Complete — PR #16 |
| 10.3 | Deterministic adversarial assurance | Complete — PR #18 |
| 10.4 | Optional OpenAI-compatible non-streaming adapter | Complete — PR #20 |

The completed Phase 10 implementation is included in `main` at and after merge commit:

```text
6125964b03e76277f42df1d60c52933e7ce0e861
```

Phase 10 is assigned project version `v0.11.0`. Phase 11 is not defined.

This document records the intent and security boundaries that governed the implementation. Current public architecture, security and assurance details are in:

- [`README.md`](README.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`THREAT_MODEL.md`](THREAT_MODEL.md)
- [`SECURITY.md`](SECURITY.md)
- [`docs/ASSURANCE.md`](docs/ASSURANCE.md)

## Goal

Build a separate, bounded agent process that can ask a hosted language model for investigation guidance and use only the MCP tools advertised by the existing native server.

The design preserves the boundary established before Phase 10:

- the C++ server remains stdio-only, network-free and credential-free;
- hosted-provider access belongs to the external Python agent;
- provider output is untrusted;
- every tool proposal is validated locally;
- normal CI and merge evidence remain deterministic, offline and credential-free;
- live provider access is optional, manual, synthetic, redacted and non-gating.

## Non-goals

Phase 10 does not authorize:

- networking or credentials inside the native C++ server;
- shell execution;
- arbitrary filesystem paths;
- raw PIDs, process discovery or process control;
- raw process memory;
- model-defined MCP methods or tools;
- automatic execution of free-form provider text;
- automatic host-evidence egress;
- streaming;
- parallel MCP execution;
- a fixed dependency on NVIDIA NIM, OpenAI or one model;
- a live provider as a CI or release dependency;
- release or tag creation as part of the Phase 10 implementation itself.

## Architecture boundaries

### Native MCP server

The native executable keeps the existing authority:

- newline-delimited JSON-RPC 2.0 over stdio;
- closed MCP lifecycle and tool schemas;
- runtime-policy-gated read-only tools;
- bounded work, cancellation and deadlines;
- no provider credentials or networking.

### External agent

The Python agent owns:

1. minimal child-environment construction;
2. MCP child lifecycle;
3. exact `tools/list` capture;
4. provider-neutral request construction;
5. proposal validation and local authorization;
6. stable request and action correlation;
7. serial at-most-once MCP execution;
8. validated evidence and provenance;
9. bounded deterministic transcripts;
10. turn, call, byte, retry, cancellation and wall-clock budgets.

### Provider adapter

The optional OpenAI-compatible adapter owns:

- configurable endpoint and model;
- production verified HTTPS;
- credential loading at explicit execution time;
- bounded non-streaming HTTP;
- content-type and response-size enforcement;
- failure classification and bounded retries;
- closed provider-specific response parsing.

The adapter never executes a tool directly.

## Environment and credential isolation

Before starting the native server or another child, the external agent builds a new environment from a minimal explicit allowlist.

It excludes provider secrets, Authorization material, secret-store tokens, proxy credentials, live-provider configuration and secret-disclosing debug variables.

Production credentials:

- are loaded only in the external provider process;
- load only at explicit verified-HTTPS execution;
- enter only the bounded provider Authorization header;
- never enter native child environment, argv, transcript or evidence.

The deterministic loopback HTTP path is explicit, loopback-only and structurally credential-free.

## Endpoint, redirect and TLS policy

Production provider endpoints must:

- use verified HTTPS;
- reject URL user-info, fragments, queries and ambiguous forms;
- verify certificate and hostname;
- reject disabled verification;
- reject redirects;
- re-resolve immediately before connection;
- reject an answer set containing a non-global destination.

The fake provider may use plain HTTP only under explicit loopback test authority and without a live credential.

## Provider request and response contracts

The provider-neutral request contains only:

- configured model identifier;
- bounded messages;
- exact advertised tool definitions;
- bounded generation controls;
- maximum output budget;
- project-owned correlation ID.

The accepted provider response is one of:

- a final assistant message;
- one or more structured tool-call proposals;
- a classified provider failure.

Unknown fields, malformed JSON, duplicate keys, mixed final-text/tool-call ambiguity, unsupported content, missing IDs, invalid tool names and malformed arguments fail closed.

## Proposal authority

The provider can propose but cannot authorize.

Every proposal must pass:

- project-owned call-ID validation;
- exact membership in the captured tool surface;
- closed argument-schema validation;
- byte, nesting and collection limits;
- immutable local authorization;
- stable action identity;
- duplicate and replay checks.

Only a locally constructed `tools/call` request can reach MCP execution.

## Action identity, replay and retries

Provider transport retries reuse one stable request correlation ID.

Local action identity derives from validated tool name, canonical arguments, captured surface and investigation context. Provider call ID alone is insufficient.

Completed, in-flight and ambiguous action identities reject:

- duplicate IDs;
- changed content under one ID;
- identical content under different IDs;
- later-turn replay;
- replay after ambiguous MCP transmission or completion.

Provider retries may repeat the provider HTTP request only before tool execution. They must never repeat an MCP action automatically.

## Multiple tool calls

Valid proposals execute serially in provider-declared order.

After the first rejection, failure, cancellation or timeout:

- later calls are skipped;
- they are not authorized;
- no MCP request is written for them;
- they do not become evidence or completed actions.

Parallel MCP execution requires a separate future threat-model decision.

## Evidence and transcripts

Provider text is guidance, never evidence.

Validated evidence must retain:

- project-owned action identity;
- exact correlated MCP response ID;
- closed and redacted result content;
- explicit provenance.

Transcripts use closed per-event schemas, bounded project-owned metadata and deterministic terminal-space reservation.

Parsing rejects orphan, stale, duplicate, mismatched and nonexistent action/response references.

## Data-flow policy

The implemented Phase 10.4 mode is:

### `synthetic-only`

Only project-authorized committed or generated synthetic material may leave through the provider adapter.

Authorization is non-transferable and bound to the exact approved message content. Plain strings, copied state and post-authorization mutation fail closed.

Later MCP evidence is blocked in this mode.

`redacted-summary` and `approved-evidence` remain unimplemented.

## Budgets and failure taxonomy

The implementation exposes safe defaults and hard ceilings for:

- total agent wall-clock time;
- provider connect, read and total timeouts;
- provider attempts and backoff;
- provider request and response bytes;
- turns, calls per turn and total calls;
- MCP request and response bytes;
- transcript bytes;
- child stdout and stderr bytes;
- startup, initialize, tools-list, MCP-call and shutdown deadlines.

The failure taxonomy distinguishes configuration, credentials, endpoint policy, TLS, redirects, DNS/connect/read/total timeouts, content type, request size, HTTP status classes, malformed/duplicate/truncated/unsupported/oversized responses, invalid proposals, replay, retry exhaustion, cancellation and local MCP failures.

Only authorized transient classes retry, within attempt and remaining-time budgets. Valid bounded `Retry-After` is honored without exceeding the remaining deadline.

## Delivery record

### Phase 10.1 — contracts and deterministic provider double

Implemented:

- provider-neutral types;
- complete failure taxonomy;
- closed schemas;
- bounded non-streaming transport seam;
- loopback fake HTTP provider;
- endpoint/TLS/redirect policy;
- environment scrubbing;
- redaction and transcript primitives;
- security regressions.

### Phase 10.2 — bounded MCP orchestration

Implemented:

- scrubbed child process lifecycle;
- initialize and exact tool-surface capture;
- immutable authorization;
- stable action identity;
- serial at-most-once execution;
- bounded turns, calls, bytes and deadlines;
- cancellation and shutdown;
- validated evidence and deterministic control transcript.

### Phase 10.3 — adversarial assurance

Added deterministic coverage for:

- hostile provider and MCP data;
- fabricated evidence and false claims;
- correlation and nonexistent references;
- replay and ambiguous completion;
- stop-after-first-control-failure behavior;
- retry delay boundaries;
- secret sentinels;
- endpoint/TLS/redirect attacks;
- transcript tampering;
- exact-at-limit and one-over budgets;
- lifecycle and authority containment.

### Phase 10.4 — optional OpenAI-compatible adapter

Implemented:

- configurable endpoint and model;
- project-owned bounded provider marker;
- verified-HTTPS production transport;
- credential-free loopback test transport;
- bounded OpenAI-compatible request/response mapping;
- classified errors and retries;
- synthetic-only egress authorization;
- manual synthetic redacted smoke;
- offline credential-free automated tests.

## Verification gate

Every Phase 10 increment required:

- focused tests;
- all earlier Phase 10 regressions;
- dev, sanitizer and ThreadSanitizer CTest suites;
- deterministic fuzz smoke;
- five libFuzzer smoke targets;
- `git diff --check`;
- exact-head GitHub Actions;
- independent exact-head review before merge.

The final Phase 10.4 evidence is summarized in [`docs/ASSURANCE.md`](docs/ASSURANCE.md).

## Release policy

The completed Phase 10 implementation is merged but untagged.

The release discipline for shipped Phase 10 work is recorded in [`docs/RELEASING.md`](docs/RELEASING.md).
