# Security policy

## Supported versions

The project is before version 1.0.
Only the latest tagged release and the default branch receive security corrections.

Release `v0.8.0` accepts local MCP traffic through standard input and standard output.
A `0.9.0` Phase 8 candidate adds a read-only demonstration client.
A trusted policy can enable read-only log, ELF, and process-memory tools.

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

- credentials
- confidential data
- local absolute paths
- build output
- release archives
- raw crash dumps
- unreviewed fuzz artifacts
