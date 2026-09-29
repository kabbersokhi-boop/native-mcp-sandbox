# Native MCP Sandbox

**Inspect Linux evidence without giving an AI a shell.**

[![CI](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kabbersokhi-boop/native-mcp-sandbox)](https://github.com/kabbersokhi-boop/native-mcp-sandbox/releases/latest)
[![C++20](https://img.shields.io/badge/C%2B%2B-20-00599C?logo=cplusplus)](CMakeLists.txt)
[![Platform: Linux](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://www.kernel.org/)
[![License](https://img.shields.io/github/license/kabbersokhi-boop/native-mcp-sandbox)](LICENSE)

Native MCP Sandbox is a **C++20 MCP authority boundary** for read-only Linux evidence. An operator decides which logs, ELF files, and processes are visible. Clients operate through a four-tool MCP surface instead of receiving a shell, arbitrary host filesystem access, process discovery, or native-server network authority.

A separate Python investigation client can optionally use an OpenAI-compatible provider, but provider output is untrusted: it must pass the captured MCP tool surface, closed schemas, local authorization, and replay checks before any tool call is executed.

> **Scope:** this is a capability-bounded evidence server. It is **not** a process, container, VM, or kernel sandbox.

**No shell** · **No arbitrary host paths** · **No client-supplied PIDs** · **Native server is stdio-only** · **Bounded work and output** · **Replay-protected agent actions**

## Why this exists

Many AI-assisted diagnostic systems solve investigation by giving the model a general-purpose execution surface: a shell, broad filesystem access, process enumeration, or a remote administration API.

This project explores a smaller security question:

> **Can an AI-assisted investigation inspect useful host evidence without receiving general host authority?**

The answer here is an intentionally narrow MCP server. The operator maps symbolic policy entries to approved resources, and the client can only invoke read-only tools inside that policy.

| The client can request | The client does not receive |
| --- | --- |
| Search within an approved log root | A shell or command execution |
| Tail bounded lines from an approved log | Arbitrary absolute host paths |
| Inspect metadata for an approved ELF file | ELF execution or loading |
| Read aggregate counters for a named process | Raw PIDs, process discovery, maps, environment, command line, or raw memory |
| Structured MCP calls over stdio | Native-server sockets, provider credentials, or model-defined tools |

With no trusted runtime policy, the server advertises **no host-evidence tools**.

## Trust boundary

~~~mermaid
flowchart LR
    P[Optional model provider]
    A[Bounded Python investigation client]
    S[C++20 MCP authority boundary]
    O[Operator policy]
    L[Approved logs]
    E[Approved ELF metadata]
    M[Approved process counters]

    P -->|untrusted structured proposal| A
    A -->|validated JSON-RPC over stdio| S
    O -->|symbolic roots and process aliases| S
    S --> L
    S --> E
    S --> M
~~~

The **native C++ server is the host authority boundary**. It owns MCP lifecycle validation, runtime policy, filesystem/process identity checks, bounded scheduling, cancellation/deadlines, and tool output.

The **Python client is outside that boundary**. It can orchestrate investigations and optionally talk to a hosted provider, but it cannot add tools or permissions to the native server.

Provider text is guidance, **not evidence**. Only validated MCP results can become MCP evidence.

For the full design, see [Architecture](ARCHITECTURE.md) and the [Threat Model](THREAT_MODEL.md).

## Quick start

Requirements: Linux, CMake 3.20+, Ninja, GCC or Clang with C++20 support, Python 3, and nlohmann/json 3.11+.

~~~bash
sudo apt-get update
sudo apt-get install --yes build-essential cmake ninja-build nlohmann-json3-dev python3

git clone https://github.com/kabbersokhi-boop/native-mcp-sandbox.git
cd native-mcp-sandbox

cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure
~~~

Check the native binary:

~~~bash
./build/dev/native-mcp-sandbox --version
./build/dev/native-mcp-sandbox --self-check
~~~

Then reproduce the deterministic investigation:

~~~bash
mkdir -p build/agent-investigation-output

python3 scripts/run_agent_investigation_demo.py \
  --server ./build/dev/native-mcp-sandbox \
  --fixture ./demo/investigation/application.log \
  --output-dir ./build/agent-investigation-output
~~~

The demo uses the **real C++ server**, a generated runtime policy, committed synthetic incident evidence, and canonical output. It requires **no hosted model, credential, or internet connection**.

Output:

~~~text
build/agent-investigation-output/report.json
build/agent-investigation-output/report.md
~~~

Committed reference output lives in [`demo/investigation/`](demo/investigation/).

## Demo: investigate `INC-042`

The synthetic incident models a service restart followed by an authentication failure, a bounded retry, recovery, and a healthy final state.

The client completes the MCP lifecycle, verifies the advertised tool surface, then performs this fixed investigation:

| Request | Tool | Evidence produced |
| ---: | --- | --- |
| `10` | `logs.search` for `INC-042` | Five matching incident lines |
| `11` | `logs.search` for `ERROR` | One authentication failure |
| `12` | `logs.tail`, last 3 lines | Retry → authentication recovery → healthy |
| `13` | `elf.inspect` on `sample.elf` | `ELF64`, `x86_64`, executable identity |
| `14` | `proc.memory` on process alias `server` | Aggregate counters observed with strict pidfd pinning |

Canonical conclusion:

~~~text
healthy_final_state_confirmed
~~~

The report intentionally stores stable predicates instead of runtime-specific PIDs, addresses, temporary paths, or volatile process values.

### What this demonstration establishes

For the tested build, the deterministic demo:

1. starts the real native server over stdio;
2. completes the MCP lifecycle;
3. verifies the exact advertised tool surface;
4. performs bounded log, ELF, and process observations;
5. correlates responses by JSON-RPC ID;
6. converts runtime observations into stable predicates;
7. emits canonical JSON and Markdown reports; and
8. reproduces byte-identical output across repeated runs.

It does **not** claim autonomous incident response, production monitoring, or proof that every security defect is absent. It is one bounded investigation over synthetic evidence.

See [Demonstrations](docs/DEMO.md) for the deterministic demo and the separate optional OpenAI-compatible synthetic smoke.

## Four read-only tools

| Tool | Purpose | Deliberate boundary |
| --- | --- | --- |
| `logs.search` | Search one approved log for literal text | Approved root + relative path only; bounded matches |
| `logs.tail` | Read a bounded preview of final log lines | No watch mode; bounded output |
| `elf.inspect` | Parse selected ELF32/ELF64 metadata | Never executes or loads the target |
| `proc.memory` | Read aggregate counters for one named process | No raw PID input, discovery, maps, environment, command line, descriptors, or raw memory |

The tool surface is intentionally small. Adding authority is treated as a security-design change, not a convenience feature.

## Security model

### Filesystem containment

Filesystem tools operate below operator-approved roots.

Strict mode uses Linux `openat2` with:

- `RESOLVE_BENEATH`
- `RESOLVE_NO_SYMLINKS`
- `RESOLVE_NO_MAGICLINKS`
- `RESOLVE_NO_XDEV`

The server validates file type, access mode, and size, then retains the accepted object through an owned descriptor.

A descriptor-walk compatibility mode exists as an explicit weaker opt-in and does not claim every strict-mode property.

### Process identity

The client selects an operator-defined process alias, never an arbitrary PID.

Strict process access combines:

- same-effective-UID validation;
- a retained `/proc/<pid>` directory descriptor;
- process start-time capture and revalidation; and
- pidfd identity pinning.

`proc.memory` exposes only bounded aggregate counters from selected procfs pseudo-files. It does not expose raw memory, process maps, command lines, environments, descriptors, or process discovery.

### Protocol and work bounds

Before normal request handling, protocol JSON is bounded by:

- **1 MiB** input;
- **64** nested containers; and
- **32,768** tokens.

The native scheduler uses:

- **2 fixed worker threads**;
- at most **16 unfinished tool calls**;
- a **30-second** deadline for each accepted native call;
- duplicate in-flight request-ID rejection;
- bounded request and response sizes; and
- a single serialized protocol writer.

Cancellation is cooperative. The project does not claim hard real-time interruption of arbitrary system calls.

### Agent authorization and replay protection

The external Python investigation client:

1. initializes the server;
2. captures and freezes the exact `tools/list` surface;
3. validates provider proposals against captured names and closed schemas;
4. derives a project-owned action identity;
5. rejects duplicates, replays, and ambiguous repeats;
6. executes accepted calls serially; and
7. validates MCP responses before they become evidence.

A provider cannot directly execute a tool. Later proposals in the same provider response are not executed after the first rejection, failure, cancellation, or timeout.

### Provider isolation

Hosted-provider networking exists only in the optional external Python adapter, never in the C++ authority process.

Production provider access requires verified HTTPS. The adapter applies endpoint validation, bounded request/response sizes, redirect rejection, DNS re-resolution immediately before TLS, and rejection when any resolved production address is non-global.

Normal CI and the primary demo do not require provider access or credentials.

## Runtime policy

The operator supplies a trusted policy that maps symbolic names to approved roots and processes.

Example:

~~~json
{
  "version": 2,
  "roots": [
    {
      "name": "evidence",
      "path": "/srv/approved-evidence",
      "maxFileBytes": 16777216
    }
  ],
  "processes": [
    {
      "name": "server",
      "pid": "self"
    }
  ]
}
~~~

Run the server with:

~~~bash
./build/dev/native-mcp-sandbox --policy-config ./policy.json
~~~

The server uses newline-delimited JSON-RPC 2.0 over standard input/output and targets MCP revision `2025-11-25`.

## Assurance

The project tests the authority boundary as an adversarial interface, not only as a happy-path API.

| Layer | Evidence |
| --- | --- |
| Protocol + integration | MCP lifecycle, runtime policy, tool schemas, response correlation, real stdio process |
| Negative + adversarial | Malformed JSON, duplicate keys, unknown fields, oversized input, replay, fabricated evidence, transcript tampering |
| Memory safety | ASan, UBSan, leak checks |
| Concurrency | Focused ThreadSanitizer runs and orchestration stress |
| Fuzzing | Deterministic mutation smoke + five Clang libFuzzer targets |
| Determinism | Repeated canonical transcript/report equality |
| Provider isolation | Loopback fake transport, TLS/endpoint policy, credential handling, synthetic-egress checks |
| Delivery | Packages, SPDX SBOMs, checksums, build provenance |

### `v0.12.1` validation snapshot

The recorded release-candidate gate includes:

- OpenAI-compatible adapter tests: **16**
- adversarial agent tests: **34**
- bounded orchestration tests: **35**, including a real Python-client/C++-server contract check
- provider-contract tests: **25**
- provider security regressions: **10**
- CTest `dev`: **21/21**
- CTest `sanitizers`: **21/21**
- CTest `thread-sanitizer`: **21/21**
- deterministic fuzz smoke: **100,000 iterations**
- libFuzzer smoke: **2,000 runs each** across protocol, runtime policy, ELF, log, and process parsing
- `git diff --check`: passed

These checks are evidence for the tested source and environments, not proof that the project has no defects.

See [Assurance and verification](docs/ASSURANCE.md) and [Fuzzing](docs/FUZZING.md) for exact commands, scope, historical campaigns, and limitations.

## Release integrity

Current documented release: **`v0.12.1`**.

The release workflow publishes:

- a Linux x86-64 native package;
- the external Python client as a wheel and source archive;
- SPDX JSON SBOMs;
- `SHA256SUMS` for downloadable assets; and
- GitHub build-provenance attestations.

Use the [latest GitHub Release](https://github.com/kabbersokhi-boop/native-mcp-sandbox/releases/latest) for evaluated artifacts. Source builds remain the portable option for other Linux architectures.

Release-specific notes: [`docs/releases/v0.12.1.md`](docs/releases/v0.12.1.md).

## Architecture at a glance

~~~text
Optional hosted provider
        |
        | verified HTTPS, bounded non-streaming JSON
        v
External Python investigation client
        |
        | validated newline-delimited JSON-RPC 2.0
        v
Native C++20 MCP server
        |
        +--> trusted runtime policy
        +--> logs.search / logs.tail
        +--> elf.inspect
        +--> proc.memory
~~~

The native request path is deliberately staged:

~~~text
bounded input
    -> JSON safety preflight
    -> MCP lifecycle + closed schema
    -> bounded work admission
    -> fixed worker pool
    -> runtime policy gate
    -> cancellation/deadline checks
    -> serialized JSON-RPC response
~~~

For implementation details, concurrency semantics, provenance rules, and provider transport, read [ARCHITECTURE.md](ARCHITECTURE.md).

## Code tour

| Area | Path |
| --- | --- |
| MCP lifecycle and request handling | [`src/server.cpp`](src/server.cpp) |
| Bounded scheduling and cancellation | [`src/orchestration.cpp`](src/orchestration.cpp) |
| Runtime policy | [`src/runtime_config.cpp`](src/runtime_config.cpp) |
| Filesystem containment | [`src/file_policy.cpp`](src/file_policy.cpp) |
| Log evidence | [`src/log_analysis.cpp`](src/log_analysis.cpp) |
| ELF inspection | [`src/elf_analysis.cpp`](src/elf_analysis.cpp) |
| Process counters | [`src/process_memory.cpp`](src/process_memory.cpp) |
| External Python client | [`agent/native_mcp_agent/`](agent/native_mcp_agent/) |
| Adversarial + integration tests | [`tests/`](tests/) |
| Fuzz targets | [`fuzz/`](fuzz/) |
| Architecture decisions | [`docs/adr/`](docs/adr/) |

## Explicit non-claims

Native MCP Sandbox does not claim:

- process, container, VM, or kernel isolation;
- arbitrary-command sandboxing;
- hard real-time cancellation;
- fairness between multiple clients;
- durable replay protection across separate investigations;
- universal OpenAI-compatible provider interoperability;
- protection against a compromised kernel or toolchain; or
- proof of complete correctness or security.

Compatibility filesystem/process modes are intentionally weaker than strict modes and are documented as such.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Threat Model](THREAT_MODEL.md)
- [Security Policy](SECURITY.md)
- [Demonstrations](docs/DEMO.md)
- [Assurance and verification](docs/ASSURANCE.md)
- [Engineering Highlights](docs/ENGINEERING_HIGHLIGHTS.md)
- [MCP orchestration](docs/MCP_ORCHESTRATION.md)
- [OpenAI-compatible adapter](docs/OPENAI_COMPATIBLE_ADAPTER.md)
- [Fuzzing](docs/FUZZING.md)
- [Contributing](CONTRIBUTING.md)

Security-sensitive changes should be reviewed against the architecture and threat model before implementation. To report a vulnerability, follow [SECURITY.md](SECURITY.md) rather than opening a public exploit report.

Licensed under the [Apache License 2.0](LICENSE).
