# Architecture

## Overview

Native MCP Sandbox separates host authority, agent orchestration and hosted-provider access into distinct trust boundaries.

```text
Optional hosted provider
        |
        | verified HTTPS, bounded non-streaming JSON
        v
External Python agent
        |
        | newline-delimited JSON-RPC 2.0 over stdio
        v
Native C++ MCP server
        |
        +--> trusted runtime policy
        +--> logs.search / logs.tail
        +--> elf.inspect
        +--> proc.memory
```

The native server remains stdio-only, network-free and credential-free. The optional OpenAI-compatible adapter exists only in the external Python agent. Provider output is untrusted and cannot directly execute a tool or become evidence.

Project version `v0.11.0` includes a preview external agent and optional provider adapter. The
native server authority remains unchanged.

## Trust boundaries

### Native server

The C++ server owns:

- MCP lifecycle and JSON-RPC framing;
- closed request and tool schemas;
- runtime-policy enforcement;
- filesystem and process identity controls;
- bounded scheduling, cancellation and deadlines;
- complete serialized protocol output.

It does not own:

- hosted-provider networking;
- provider credentials;
- arbitrary shell, filesystem or process authority;
- model-defined methods or tools.

### Runtime policy

The operator supplies a trusted policy that maps symbolic names to approved resources. The MCP client selects a symbolic name; it cannot choose an arbitrary absolute path or raw PID.

With no policy, the server advertises no host tools.

### External agent

The Python agent owns:

- child-process startup with a scrubbed environment;
- MCP initialize and `tools/list` capture;
- immutable tool-surface identity;
- provider request construction;
- local tool proposal validation and authorization;
- stable action identity and replay state;
- serial, at-most-once MCP execution;
- validated evidence and deterministic control transcripts.

### OpenAI-compatible adapter

The optional adapter owns bounded provider HTTP, TLS, authentication, retries, content-type validation and provider-specific response parsing.

Production access requires verified HTTPS. Endpoint and model remain configurable. Credentials load only at explicit production execution. The loopback fake-provider path is credential-free.

The adapter is non-streaming. Normal CI does not require internet access or credentials.

## Native request path

The server processes one request in this sequence:

1. The main thread reads one size-limited JSON-RPC line from standard input.
2. SAX preflight checks syntax, duplicate keys, depth and token count.
3. The protocol layer validates lifecycle state and the closed request schema.
4. Immediate protocol or discovery responses are serialized directly.
5. A valid `tools/call` reserves one unfinished-work slot.
6. A C++20 coroutine suspends into reserved queue storage.
7. One fixed worker resumes the coroutine.
8. The selected analyzer applies its runtime-policy gate.
9. Cancellation and deadline checks run at bounded points.
10. One serialized writer emits a complete JSON-RPC response line.

Tool calls can complete out of request order. Clients must correlate each response by JSON-RPC ID.

## JSON and resource bounds

`preflight_json` uses the nlohmann/json SAX interface before DOM construction.

Protocol JSON limits:

- 1 MiB input;
- 64 nested containers;
- 32,768 tokens.

Runtime-policy JSON limits:

- 64 KiB input;
- 32 nested containers;
- 4,096 tokens.

The server then applies closed-schema validation. The two-stage parse is intentional: preflight bounds syntax and structure; the DOM pass validates meaning.

The scheduler uses:

- two worker threads;
- at most 16 unfinished tool calls;
- a 30-second deadline for each accepted native call;
- bounded request and response sizes;
- duplicate in-flight request-ID rejection;
- reserved coroutine queue capacity.

The server does not create one thread per request.

## Filesystem boundary

Filesystem tools receive a configured root name and relative path.

Strict mode uses Linux `openat2` with:

- `RESOLVE_BENEATH`;
- `RESOLVE_NO_SYMLINKS`;
- `RESOLVE_NO_MAGICLINKS`;
- `RESOLVE_NO_XDEV`.

The policy validates file type, access mode and size, then keeps the accepted inode pinned through an owned descriptor.

The descriptor-walk compatibility mode is explicit and cannot prove every bind-mount boundary.

## Process boundary

The operator configures named process targets. The MCP client cannot provide a raw PID.

Strict process mode requires:

- the same effective UID;
- a retained `/proc/<pid>` directory descriptor;
- process start-time capture and revalidation;
- pidfd identity pinning.

`proc.memory` reads only bounded aggregate values from `status`, `statm` and optional `smaps_rollup`. It does not read raw memory, maps, command lines, environments, descriptors or discover processes.

## Cancellation and shutdown

The server accepts `notifications/cancelled` only as a notification with a valid `requestId`.

Matching work receives a cooperative stop request. The normal tool response is suppressed after client cancellation. Unknown or completed IDs are ignored.

Deadlines use `std::chrono::steady_clock`. Cancellation is cooperative; the project does not claim hard real-time interruption of arbitrary system calls.

EOF closes admission. Accepted work drains before workers join. Shutdown has one join owner, and standard output remains complete protocol lines only.

## Agent orchestration path

The external agent performs this bounded sequence:

1. Construct a minimal child environment.
2. Start the native server without a shell.
3. Send `initialize` and validate the correlated response.
4. Send `notifications/initialized`.
5. Request `tools/list` and freeze the exact advertised surface.
6. Construct a bounded provider-neutral request.
7. Receive either a final message or structured tool proposals.
8. Validate every proposal against the captured name and closed input schema.
9. Derive a project-owned action identity.
10. Reject duplicates, replays and ambiguous repeats.
11. Execute accepted calls serially in provider-declared order.
12. Validate MCP responses before creating evidence.
13. Record deterministic, bounded transcript events.
14. Stop at configured turn, call, byte, cancellation or wall-clock limits.

Later proposals in one provider response do not execute after the first rejection, failure, cancellation or timeout.

## Evidence and provenance

Provider text is guidance, not evidence.

Validated evidence retains:

- a project-owned action identity;
- the correlated MCP response ID;
- closed and redacted result content;
- explicit `VALIDATED_MCP_EVIDENCE` provenance.

Transcript parsing validates both event schemas and cross-event action/response references. Orphan, mismatched, stale, duplicate and nonexistent provenance references fail closed.

## Provider transport

The OpenAI-compatible adapter:

- maps only provider-neutral request fields;
- forces `stream: false`;
- derives tool definitions from the captured MCP surface;
- enforces request bytes before transmission;
- bounds response bytes while reading;
- validates JSON content type;
- rejects redirects;
- classifies HTTP/TLS/timeout failures through the project taxonomy;
- applies bounded retries and `Retry-After` rules;
- parses a closed response envelope into existing neutral types.

Production DNS is re-resolved immediately before TLS connection. Any non-global answer rejects the destination. TLS hostname verification uses the configured public hostname even when the socket connects to a validated resolved address.

## Synthetic-only egress

Automated tests and the manual smoke use the `synthetic-only` policy.

Outbound initial content must carry project-issued, non-transferable synthetic authorization. Arbitrary strings, copied authorization state and mutated content fail closed. Later MCP evidence is not sent to the provider in this mode.

## Demonstrations

The deterministic offline investigation client uses the real server, committed synthetic evidence and canonical JSON/Markdown reports. It validates the exact tool surface and produces byte-identical outputs across repeated runs.

The optional hosted-provider smoke uses only project-authorized synthetic content. It is manual, redacted, observational and non-gating.

See [`docs/DEMO.md`](docs/DEMO.md).

## Assurance design

Native and agent assurance includes:

- unit and process-level integration tests;
- accepted and rejected schema paths;
- malformed, duplicate-key and oversized data;
- replay, correlation and fabricated-evidence attacks;
- ASan, UBSan, leak detection and ThreadSanitizer;
- deterministic mutation campaigns;
- five Clang libFuzzer targets;
- strict `openat2`, pidfd, AF_UNIX and FIFO integration;
- byte-identical report and transcript checks;
- secret-sentinel coverage across owned output surfaces.

The shared fuzz support covers protocol, runtime policy, ELF, log and supplied proc-text parsing. The proc parser target does not open host procfs.

See [`docs/ASSURANCE.md`](docs/ASSURANCE.md) and [`docs/FUZZING.md`](docs/FUZZING.md).

## Residual boundaries

The project does not claim:

- hard real-time cancellation;
- fairness between multiple clients;
- durable replay state across separate investigations;
- universal OpenAI-compatible provider interoperability;
- protection against a compromised kernel or toolchain;
- proof of complete correctness or security.

New authority requires an explicit threat-model decision and focused review.
