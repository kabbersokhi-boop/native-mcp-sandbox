# Security policy

## Supported versions

Native MCP Sandbox is before version 1.0. Security corrections target:

- the latest tagged release; and
- the default branch, `main`.

The latest release is `v0.11.0`. Its tag identifies the exact release commit; release tags are never rewritten.

`v0.11.0` includes the completed Phase 10 external agent and optional OpenAI-compatible adapter. The native C++ server remains stdio-only, network-free, credential-free and exposes no new MCP tool.

## Report a vulnerability

Do not publish a working exploit or sensitive reproduction in a public issue.

Use GitHub private vulnerability reporting when available.

If private reporting is unavailable:

1. Open a public issue without exploit details.
2. Ask for a private communication channel.
3. Do not add credentials, host evidence or confidential data to the issue.

Include these details when possible:

- affected version, tag or commit;
- operating system and kernel;
- compiler and sanitizer configuration;
- minimum reproduction steps;
- minimized fuzz input, when applicable;
- fuzz target, seed, dictionary, flags and duration;
- expected behavior;
- observed behavior;
- security impact;
- current disclosure status.

The project is maintained on a best-effort basis and does not provide a service-level agreement.

## Security boundary

The project intentionally separates two components.

### Native server

The C++ MCP server owns local policy enforcement and read-only evidence access. It must remain:

- stdio-only;
- network-free;
- credential-free;
- closed-schema and bounded;
- free of generic shell, arbitrary path and raw PID authority.

### External agent

The Python agent may perform bounded provider networking, but it must:

- keep provider credentials out of the native process;
- treat provider output as untrusted;
- validate every proposed tool against the exact captured MCP surface;
- execute serially and at most once;
- retain action/response provenance;
- use explicit data-flow authorization;
- keep normal CI offline and credential-free.

## Prohibited authority changes

Do not add any of these capabilities without a separate threat-model and architecture decision:

- raw process memory;
- client-selected PIDs;
- filesystem mutation;
- arbitrary filesystem reads;
- process discovery or control;
- shell access;
- networking inside the native server;
- provider credentials inside the native server;
- provider-defined MCP methods or tools;
- parallel MCP execution;
- automatic host-evidence egress.

## Native server requirements

### Protocol and JSON

Protocol and configuration changes must retain tests for:

- accepted input;
- rejected input;
- duplicate keys;
- excessive depth;
- excessive token count;
- malformed encoding;
- request and response limits;
- closed-schema unknown-field rejection.

### Scheduler and lifecycle

Scheduler changes must retain tests for:

- saturation;
- duplicate IDs;
- queued and running cancellation;
- deadline order;
- EOF;
- worker-construction failure;
- simultaneous shutdown;
- callback failure;
- output framing.

### Filesystem and process identity

Strict filesystem mode must preserve `openat2` containment, descriptor ownership and rejection of traversal, symlinks, magic links and mount crossings.

Strict process mode must preserve same-UID checks, proc-directory retention, start-time validation and pidfd identity pinning.

## External agent requirements

### Child environment

Before starting the native server or another child, construct a minimal environment from an explicit allowlist.

Do not inherit:

- provider API keys;
- Authorization values;
- secret-store tokens;
- proxy credentials;
- live-provider configuration;
- secret-disclosing debug variables;
- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` or `NO_PROXY`, unless a child-specific policy explicitly permits a structurally validated value.

Sentinel tests must prove secret absence from owned child environments, argv, retained stdout/stderr, exceptions, diagnostics, transcripts, evidence, reports and available crash-artifact surfaces.

### Endpoint and TLS policy

Production provider endpoints must:

- use verified HTTPS;
- reject URL user-info, fragments, queries and ambiguous forms;
- verify certificate and hostname;
- reject disabled verification;
- reject redirects;
- re-resolve and reject non-global destination addresses immediately before connection.

Plain HTTP is allowed only for the explicit loopback fake provider. That path is structurally credential-free and test-only.

### Credentials

Production credentials:

- load only at explicit adapter execution;
- remain in the external provider process;
- enter only the bounded provider Authorization header;
- must not enter argv, transcripts, evidence, native child state or diagnostics.

The absence of a production credential must fail as `CREDENTIAL_UNAVAILABLE` when production execution is explicitly requested.

### Data flow

The implemented automated and manual smoke path uses `synthetic-only` egress.

Synthetic outbound content requires project-issued, non-transferable authorization. Arbitrary strings, copied authorization state and mutated content fail closed. Later MCP evidence remains blocked in this mode.

`redacted-summary` and `approved-evidence` are not implemented by Phase 10.4.

### Tool authority and replay

Provider text is guidance, never evidence.

Every tool proposal must pass:

- exact advertised-name membership;
- closed argument-schema validation;
- local authorization;
- stable action identity;
- duplicate and replay checks;
- serial execution;
- at-most-once enforcement.

Transport retries must not repeat an MCP action.

### Evidence and transcripts

Validated evidence must retain an exact project-owned action identity, correlated MCP response ID and explicit provenance.

Transcript parsers must reject unknown fields, malformed metadata, orphan references, mismatched action/response pairs, duplicate or stale provenance and appended data after terminal exhaustion.

## Verification requirements

For each confirmed crash, hang, sanitizer report, data race, secret leak or authority bypass:

1. reproduce the issue with an exact command;
2. confirm it with the relevant sanitizer or detector;
3. minimize the input or scenario;
4. correct the implementation without weakening the boundary;
5. add a named regression;
6. add a corpus input only when it provides durable new coverage.

Run the applicable normal, sanitizer, ThreadSanitizer and fuzz gates. See [`docs/ASSURANCE.md`](docs/ASSURANCE.md) and [`docs/FUZZING.md`](docs/FUZZING.md).

Longer native campaigns:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

A clean run is evidence for the exact tested source and environment. It is not proof that no vulnerability exists.

## Optional hosted-provider smoke

The OpenAI-compatible smoke is:

- disabled by default;
- manually enabled;
- synthetic-only;
- redacted;
- non-gating;
- observational.

A live provider result must not become CI, release or factual evidence.

## Do not commit

- credentials or API keys;
- secret-bearing environment files;
- confidential host evidence;
- local absolute paths;
- build output;
- release archives;
- raw crash dumps;
- unreviewed fuzz artifacts;
- live-provider request or response captures containing sensitive data.
