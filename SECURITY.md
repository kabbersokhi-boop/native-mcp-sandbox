# Security policy

## Supported versions

The project is before version 1.0.
Only the latest tagged release and the default branch receive security corrections.

The latest tagged release is `v0.10.1`, at commit
`2e19b5b6a14f5fbe26c5b4094c1750c6c5205db1`. It provides the local stdio MCP
server, the deterministic read-only investigation client, and bounded
reproducibility benchmarks. A trusted policy can enable read-only log, ELF, and
process-memory tools.

The immutable `v0.10.0` tag contains the historical stale compiled version
identifier `0.9.0`. `v0.10.1` is the correction release at the tag target above.
Phase 10.4 adds an optional bounded OpenAI-compatible adapter only in the
external Python agent. The native C++ server remains stdio-only, network-free,
credential-free, and exposes no new MCP tool. Production credentials are
restricted to verified-HTTPS adapter execution; normal CI remains offline and
credential-free.

The security scope includes these areas:

- protocol framing
- JSON preflight
- lifecycle control
- filesystem containment
- process identity
- bounded parsing
- work scheduling
- cancellation
- deadlines
- output serialization
- fuzz harnesses
- dependencies
- deterministic demonstration output
- benchmark report integrity

## Report a vulnerability

Do not put a working exploit in a public issue.
Use GitHub private vulnerability reporting.

If private reporting is not available, do these steps:

1. Open a public issue without exploit details.
2. Ask for a private communication channel.
3. Do not add confidential data to the issue.

Include this information when possible:

- affected version and commit
- operating system and kernel
- compiler and sanitizer configuration
- minimum reproduction steps
- minimized fuzz input, when applicable
- fuzz target, seed, dictionary, flags, and duration
- expected behavior
- observed behavior
- security effect
- current public-disclosure status

The maintainers respond on a best-effort basis.
This project does not provide a service-level agreement.

## Requirements for a security-related change

For a protocol or JSON change, add tests for these conditions:

- accepted input
- rejected input
- duplicate keys
- excessive depth
- excessive token count
- malformed encoding
- request and response limits

For a scheduler change, add tests for these conditions:

- saturation
- duplicate IDs
- cancellation
- deadline order
- EOF
- worker-construction failure
- simultaneous shutdown
- callback failure
- output framing

For each confirmed crash, hang, sanitizer report, or data race, add a permanent regression.
Minimize the input before you commit it.

Update the threat model when an assumption changes.
Run the applicable sanitizers.
Run focused ThreadSanitizer tests for a concurrency change.
Check object lifetime, lock order, coroutine destruction, identity, lifecycle, cancellation races, and exception cleanup.

Do not add one of these capabilities without a separate threat-model decision:

- raw process memory
- client-selected PIDs
- filesystem changes
- process control
- shell access
- networking

A hosted model provider must remain outside the native MCP server. The provider
client must be a separate process that treats model output as untrusted, rejects
unknown fields in production request/response and transcript schemas, validates
closed tool-call schemas, uses only symbolic aliases, and communicates with the
server through the existing stdio MCP interface. The native server must remain
credential-free and must not gain HTTP or other networking support.

Before starting the server or any child, the external agent must build a
deliberately scrubbed environment from a minimal allowlist. It must not inherit
provider API keys, authorization tokens or headers, secret-store tokens, proxy
credentials, live-provider configuration, secret-disclosing debug variables, or
`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` unless a child-specific
allowlist explicitly requires them. Deterministic sentinel tests must prove
that secrets do not appear in child environments, arguments, stdout, stderr,
exceptions, logs, transcripts, reports, or crash artifacts.

Production endpoints must use verified HTTPS, validate scheme and authority,
reject URL user-info and fragments, verify certificate and hostname, and reject
disabled verification and ambiguous forms. Redirects are disabled by default;
future bounded redirects must not forward credentials across origins, downgrade
HTTPS, or reach disallowed address classes. Plain HTTP is allowed only for an
explicit loopback-only fake-provider test with no live credential loaded or
sent.

The agent must use stable request correlation and locally derived action
identities, deduplicate proposals across attempts and turns, and execute each
accepted action at most once. Multiple calls are serialized in provider order;
PRs 10.1–10.3 must not execute them in parallel, and processing stops after
the first rejection, failure, cancellation, or timeout. Provider retries are
transport-only and must not repeat an MCP call.

Provider text is guidance, never evidence. Factual report claims must trace to
validated MCP response IDs, stable local predicates, committed synthetic
fixture assertions, or local control events. Reports must distinguish
suggestions, proposals, rejections, validated evidence, derived predicates,
and supported conclusions.

Normal CI has no internet access or credential requirement and uses deterministic
local provider doubles. Streaming remains deferred until non-streaming tests
pass. A live NIM smoke, if later added, must be manual, synthetic, redacted,
non-gating, and deferred until PRs 10.1–10.3 pass.

Run longer native tests with these commands:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

A clean test run is evidence for the exact tested build and paths.
It is not proof that the project has no vulnerability.

The Phase 8 demonstration uses strict `openat2` and pidfd operation.
It does not pass either legacy compatibility flag.
It does not execute or import its generated ELF fixture.
Its reports do not contain PIDs, UIDs, memory totals, addresses, temporary
paths, or runtime timestamps.

Do not commit these items:

- credentials or API keys
- environment files that contain secrets
- confidential data
- local absolute paths
- build output
- release archives
- raw crash dumps
- unreviewed fuzz artifacts
- live-provider request or response captures that contain sensitive evidence
