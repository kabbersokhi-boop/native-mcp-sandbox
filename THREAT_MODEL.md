# Threat model

## Scope

Native MCP Sandbox has two deliberately separate security boundaries:

1. the native C++ MCP server, which exposes narrow, policy-approved, read-only Linux evidence over stdio; and
2. the optional external Python agent, which can communicate with a hosted OpenAI-compatible provider while preserving local MCP authorization.

The hosted provider is never part of the native server's trusted computing base.

## Protected assets

The project protects:

- confidentiality and integrity of host files;
- confidentiality and identity of host processes;
- privacy of command lines, environments, maps, descriptors and raw memory;
- integrity and framing of MCP standard output;
- bounded CPU, memory, descriptors, threads, work, JSON and response size;
- operator control of approved roots and processes;
- provider credentials and Authorization material;
- approved and unapproved host evidence;
- MCP request/response correlation;
- action identity, replay state and at-most-once behavior;
- transcript and evidence provenance;
- endpoint, model and data-flow configuration.

## Trusted components

The project trusts:

- the reviewed executable and external agent code;
- the trusted runtime policy;
- the validated local adapter configuration;
- the operating system, kernel and procfs;
- the compiler, C++ runtime and Python runtime;
- the operator-selected roots, process aliases, provider endpoint and model;
- project-owned closed schemas and authorization state.

The project does **not** trust:

- MCP client input;
- runtime-policy text before validation;
- inspected files or procfs text;
- provider output;
- HTTP status, headers or body;
- DNS answers and remote network behavior;
- redirect targets;
- provider tool names or arguments;
- arbitrary initial prompt strings;
- evidence before schema and provenance validation;
- transcript input before closed parsing;
- request, cancellation and concurrency timing;
- fuzz corpora or artifacts.

## Native server threats

### Protocol and parser abuse

Threats include malformed JSON, duplicate keys, deep or oversized structures, unknown fields, invalid lifecycle transitions, duplicate IDs and output-framing attacks.

Controls include:

- bounded SAX preflight;
- duplicate-key rejection;
- depth, token and byte limits;
- closed request schemas;
- exact lifecycle validation;
- one serialized protocol writer;
- complete newline-delimited JSON-RPC responses.

### Filesystem escape

Threats include traversal, symlink and magic-link escape, mount crossing, file replacement and unbounded reads.

Controls include:

- no tools without a trusted policy;
- symbolic root names and relative paths;
- strict `openat2` containment;
- file type, mode and size checks;
- owned descriptor pinning;
- bounded analyzers.

The compatibility descriptor walk is an explicit weaker mode and cannot prove every bind-mount boundary.

### Process identity confusion

Threats include client-selected PIDs, PID reuse, cross-UID observation, process exit and exposure of command lines, environments, maps, descriptors or raw memory.

Controls include:

- operator-defined process aliases;
- same-effective-UID checks;
- retained proc-directory descriptors;
- start-time revalidation;
- strict pidfd pinning;
- fixed aggregate pseudo-file access only.

### Resource and lifecycle abuse

Threats include request flooding, excessive unfinished work, cancellation races, deadline races, partial worker construction and shutdown deadlocks.

Controls include:

- two fixed worker threads;
- at most 16 unfinished calls;
- reserved coroutine queue capacity;
- duplicate in-flight ID rejection;
- steady-clock deadlines;
- cooperative stop tokens;
- response suppression after cancellation;
- exception-safe worker construction;
- one shutdown/join owner;
- stress and ThreadSanitizer tests.

## External agent threats

### Credential disclosure

Threats include environment inheritance, argv leakage, plaintext loopback transmission, diagnostic echo, transcript leakage and provider response capture.

Controls include:

- minimal allowlisted child environments;
- no provider secret in the native process;
- credential loading only at explicit production HTTPS execution;
- credential use only in the bounded provider Authorization header;
- structurally credential-free loopback fake-provider operation;
- fixed diagnostics and structural redaction;
- unique sentinel tests across owned output surfaces.

### Endpoint misuse and SSRF-style behavior

Threats include insecure schemes, URL user-info, fragments or query forms, TLS disablement, redirect credential leakage, DNS rebinding and private/loopback/link-local destinations.

Controls include:

- verified HTTPS for production;
- closed endpoint validation;
- user-info, fragment and query rejection;
- redirects disabled;
- DNS re-resolution immediately before TLS connection;
- rejection when any resolved production address is non-global;
- TLS SNI and hostname verification against the configured public host;
- explicit loopback-only HTTP exception for deterministic tests.

### Provider-controlled authority

Threats include invented tool names, malformed arguments, prompt injection, fabricated evidence, unsupported factual claims and provider-selected methods.

Controls include:

- exact immutable `tools/list` capture;
- closed advertised-tool schemas;
- locally constructed `tools/call` requests only;
- project-owned authorization objects;
- provider text classified as guidance only;
- validated MCP responses as the only source of MCP evidence;
- closed result and transcript schemas.

### Replay and duplicate execution

Threats include repeated call IDs, identical content under different IDs, retries after ambiguous transmission, later-turn replay and retry amplification.

Controls include:

- stable local request correlation across transport attempts;
- action identities derived from validated content and context;
- bounded proposed, in-flight and completed state;
- duplicate and content-identical rejection;
- serial execution;
- at-most-once MCP execution;
- no automatic MCP replay after ambiguous completion.

### Data exfiltration

Threats include arbitrary host data placed in the initial prompt, later MCP evidence silently sent to a provider and copied or mutated synthetic authorization.

Controls include:

- `synthetic-only` as the implemented data-flow mode;
- project-issued, non-transferable synthetic egress authorization;
- rejection of unmarked, copied or mutated outbound message content;
- rejection of later MCP evidence in this mode;
- no implementation of `redacted-summary` or `approved-evidence` in Phase 10.4.

### Provider instability and resource abuse

Threats include oversized bodies, malformed JSON, invalid content types, slow reads, retry storms, excessive `Retry-After` and unbounded response buffering.

Controls include:

- request size enforcement before transmission;
- response limits while reading;
- connect, read and total deadlines;
- bounded attempt count and backoff;
- exact bounded `Retry-After` parsing;
- classified permanent and retryable failures;
- closed provider-response parsing;
- no streaming.

## Evidence and transcript threats

Threats include fabricated response references, mismatched action/response pairs, provider claims presented as evidence, terminal transcript mutation and secret-bearing metadata.

Controls include:

- project-owned evidence provenance;
- exact action and response correlation;
- parser-local transcript lifecycle validation;
- orphan, stale, duplicate, mismatched and nonexistent reference rejection;
- per-event closed metadata schemas;
- bounded terminal-space reservation;
- accepted-prefix immutability after transcript exhaustion;
- structural redaction and safe identifiers.

## Adversarial testing

The project includes deterministic tests for:

- malformed, duplicate-key, unknown-field, truncated and oversized data;
- provider false claims and evidence fabrication;
- wrong, future, unsolicited and duplicate response IDs;
- replay and at-most-once attacks;
- stop-after-first-rejection/failure/timeout/cancellation behavior;
- failure taxonomy and retry boundaries;
- credential and secret sentinels;
- endpoint, TLS and redirect rejection;
- transcript and provenance tampering;
- exact-at-limit and one-over budgets;
- child exit, flooding, cancellation and bounded shutdown;
- serial maximum-active-call behavior;
- deterministic repeated output.

Native deterministic fuzzing and five libFuzzer targets cover protocol, runtime policy, ELF, log and supplied proc-text parsing. Byte fuzzing does not replace strict Linux integration or concurrency testing.

See [`docs/ASSURANCE.md`](docs/ASSURANCE.md) and [`docs/FUZZING.md`](docs/FUZZING.md).

## Residual risks

- Cancellation is cooperative and cannot guarantee hard real-time interruption of every system call.
- The unfinished-work limit is process-wide, not a multi-client fairness policy.
- Process counters are non-atomic snapshots and some values are approximate.
- The compatibility filesystem mode cannot detect every bind-mount boundary.
- The compatibility process mode lacks pidfd identity pinning.
- Sanitizers and fuzzers observe only executed paths and tested configurations.
- Hosted-model output remains probabilistic and provider availability is external.
- OpenAI-compatible services can differ despite a shared API shape.
- At-most-once state lasts for one bounded investigation unless durable state is separately designed.
- Synthetic fake-provider tests cannot prove live-provider behavior.
- TLS protects transport; it does not make provider output trustworthy.
- An operator can intentionally select unsafe evidence or configuration outside project guidance.
- A privileged or compromised kernel can invalidate userspace assumptions.

A finite campaign cannot prove that defects are absent. New authority requires an explicit threat-model decision, focused implementation and independent review.
