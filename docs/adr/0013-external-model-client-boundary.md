# ADR 0013: keep hosted model access outside the MCP server

## Decision

Any hosted language-model integration must run in a separate agent or client
process. The native MCP server remains local, standard-input/standard-output
only, credential-free, and network-free.

The agent may use an OpenAI-compatible hosted API such as NVIDIA NIM for
optional development experiments. The provider is replaceable and must not be a
required dependency of the server, the deterministic test suite, normal CI, or
a release gate.

The future client must keep the endpoint and model identifier configurable and
provider-neutral. It must load an API key only from an environment variable or
secret store, never from command-line arguments. Its transport must enforce
connect, read, and total deadlines, bounded request and response sizes, and a
bounded retry count with backoff. It must handle 401, 403, 404, 408, 429, and
5xx responses explicitly. Malformed JSON, truncated streaming responses, and
provider output must be treated as untrusted failures.

## Context

The server's trust boundary intentionally excludes networking, shell access,
arbitrary paths, raw PIDs, process discovery, and broad operating-system
authority. Adding hosted model access to the server would introduce credentials,
TLS and HTTP dependencies, remote availability, provider-controlled data
handling, and a new untrusted input surface inside the most security-sensitive
component.

Hosted model output is probabilistic and externally controlled. A free or
shared development endpoint may be throttled, changed, or unavailable. It
cannot provide deterministic merge evidence.

The existing deterministic demonstration client already demonstrates the correct separation: a
bounded client starts the real server, communicates over MCP stdio, validates
closed response schemas, correlates request IDs, and emits stable evidence.

## Architecture

The external process owns these responsibilities:

- provider endpoint and model configuration;
- API-key loading from an environment variable or secret store;
- HTTP transport, deadlines, retries, and provider error handling;
- parsing model responses and tool-call suggestions;
- closed-schema validation of every proposed tool action;
- orchestration of MCP requests over the server's existing stdio interface;
- bounded, redacted transcripts suitable for testing and review.

The native server continues to own these responsibilities:

- MCP protocol and lifecycle validation;
- operator-defined symbolic resource aliases;
- closed tool schemas;
- filesystem and process policy enforcement;
- bounded scheduling, cancellation, deadlines, parsing, and output;
- no networking and no credential handling.

## Required controls

The agent must treat model output, provider errors, streamed fragments, tool
arguments, and returned evidence as untrusted.

It must not:

- execute model text as a shell command;
- permit raw filesystem paths or PIDs;
- invent an MCP method or tool that the server did not advertise;
- retry without a fixed attempt and time budget;
- send secrets, host paths, process identifiers, or confidential evidence to a
  hosted provider unless an operator has explicitly approved that data flow;
- write API keys to arguments, logs, fixtures, reports, exceptions, or recorded
  transcripts;
- make live-provider access a required CI or release condition.

Normal CI must use deterministic local provider doubles. Tests must cover valid
responses, malformed JSON, invalid tool calls, unexpected fields, streaming
fragmentation, rate limits, authentication failure, server errors, timeouts,
connection loss, oversized output, retry exhaustion, cancellation, and secret
redaction. Tool-call validation must use a closed schema and an exact
allowlist of advertised tools. The client must not create raw paths or PIDs,
execute a shell, or widen the server's advertised MCP surface. Deterministic
fake-provider tests must cover each of these controls before any optional manual
live smoke is considered.

A live provider smoke test may be manually triggered and separately gated. It
must use a repository secret, bounded synthetic input, and no production host
evidence. A live smoke result is observational only.

## Consequences

The server's existing trust boundary and dependency surface remain unchanged.
Provider integration can evolve independently and can be disabled entirely.
Deterministic tests remain reproducible without internet access or credentials.

The agent becomes a separate security boundary. Its threat model must cover
credential disclosure, remote data exposure, prompt injection, fabricated
evidence, invalid tool selection, provider instability, retry amplification,
and transcript leakage.

## Alternatives rejected

### Add HTTP and NIM support to the C++ server

Rejected because it adds networking, credentials, remote dependencies, and
probabilistic orchestration to the component that currently enforces narrow
local authority.

### Require a live provider in normal CI

Rejected because hosted development endpoints are external, mutable, and
potentially rate-limited. They cannot provide deterministic merge evidence.

### Accept model-generated raw commands or paths

Rejected because this bypasses symbolic aliases and closed MCP tool schemas.
