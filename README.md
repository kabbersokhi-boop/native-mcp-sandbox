# Native MCP Sandbox

> A security-first C++20 MCP server that gives AI agents narrow, read-only access to Linux evidence.

[![CI](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/kabbersokhi-boop/native-mcp-sandbox/actions/workflows/ci.yml)
[![Tag](https://img.shields.io/github/v/tag/kabbersokhi-boop/native-mcp-sandbox?label=tag)](https://github.com/kabbersokhi-boop/native-mcp-sandbox/tags)
[![License](https://img.shields.io/github/license/kabbersokhi-boop/native-mcp-sandbox)](LICENSE)
[![C++20](https://img.shields.io/badge/C%2B%2B-20-blue.svg)](https://en.cppreference.com/w/cpp/20)
[![Linux](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](https://www.kernel.org/)

Native MCP Sandbox explores a practical question:

**How can an AI agent inspect useful host evidence without receiving a shell, arbitrary file access, raw process memory, or broad operating-system authority?**

The answer in this repository is a small native server with a deliberately narrow trust boundary. An operator chooses the files and processes that can be observed. The MCP client can then use four bounded, read-only tools through standard input and standard output.

The latest tagged release is **v0.10.0**. Phases 0–9 are complete and released
through this tag. The current main-line correction prepares **v0.10.1**.
Phase 10 has not started.

## Why this project exists

Many agent tools begin with a powerful primitive such as a shell, a filesystem browser, or a general process API. That approach is convenient, but it also creates a large security boundary.

Native MCP Sandbox takes the opposite approach:

- expose a small set of purpose-built tools;
- require explicit operator policy;
- accept symbolic names instead of raw paths and PIDs;
- enforce fixed resource limits;
- fail closed when strict kernel protections are unavailable;
- test malformed input, races, cancellation, and resource pressure as first-class behavior.

This project is useful as:

- a reference for secure MCP tool design;
- a portfolio example of modern C++ systems engineering;
- a study of Linux descriptor and process-identity controls;
- a reproducible demonstration of deterministic agent evidence collection;
- a foundation for future benchmark and interoperability work.

## What the server can do

A trusted runtime policy can enable four tools.

| Tool | Purpose | Important boundary |
| --- | --- | --- |
| `logs.search` | Search one approved log file for literal text | No recursive search or arbitrary paths |
| `logs.tail` | Read bounded previews of final log lines | No file watching or unbounded output |
| `elf.inspect` | Inspect selected ELF32 and ELF64 metadata | The target is never executed or loaded |
| `proc.memory` | Read aggregate memory counters for one named process | No raw memory, maps, command line, environment, or process discovery |

Without a policy, the server exposes no host tools.

## What makes it different

### The client does not choose raw authority

The MCP client selects operator-defined names such as `evidence` or `server`. It cannot submit an arbitrary absolute path or raw PID.

### Files stay inside approved roots

Strict filesystem mode uses Linux `openat2` with containment controls for traversal, symbolic links, magic links, and mount crossings. Accepted files remain pinned through owned descriptors.

### Process identity is pinned

Strict process mode requires the same effective UID and a pidfd. The server also retains the process directory and revalidates process identity before and after each observation.

### Work is bounded

The server uses a fixed two-worker scheduler. It limits unfinished calls, request size, response size, JSON depth, token count, file reads, search results, and tool deadlines.

### Failure is part of the design

The test suite covers malformed JSON, duplicate keys, oversized input, policy denial, process exit, cancellation, deadline races, saturation, worker-construction failure, concurrent shutdown, and output framing.

## Deterministic investigation demonstration

The current main-line correction preparing v0.10.1 includes a complete
investigation client that uses the real server.

The demonstration:

1. starts `native-mcp-sandbox` through its MCP stdio interface;
2. loads one synthetic incident log;
3. creates one non-executable ELF fixture;
4. verifies the exact four-tool surface;
5. runs a fixed sequence of log, ELF, and process observations;
6. correlates responses by JSON-RPC ID, even when they complete out of order;
7. writes canonical JSON and Markdown reports;
8. proves that two independent runs produce byte-identical output.

The scenario follows a service restart, an authentication failure, a bounded retry, recovery, and a healthy final state.

The report contains stable evidence only. It excludes runtime PIDs, UIDs, memory totals, temporary paths, addresses, and current timestamps.

## Quick start

### Requirements

- Linux
- CMake 3.20 or newer
- Ninja
- GCC or Clang with C++20 support
- Python 3
- nlohmann/json 3.11 or newer
- procfs
- Linux `openat2` support
- pidfd support for strict process mode

On Ubuntu, install the common build dependencies:

```bash
sudo apt-get update
sudo apt-get install --yes build-essential cmake ninja-build nlohmann-json3-dev python3
```

### Build and test

```bash
git clone https://github.com/kabbersokhi-boop/native-mcp-sandbox.git
cd native-mcp-sandbox

cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure
```

Check the executable:

```bash
./build/dev/native-mcp-sandbox --version
./build/dev/native-mcp-sandbox --self-check
```

### Run the deterministic demonstration

```bash
mkdir -p ./build/agent-investigation-output

python3 scripts/run_agent_investigation_demo.py \
  --server ./build/dev/native-mcp-sandbox \
  --fixture ./demo/investigation/application.log \
  --output-dir ./build/agent-investigation-output
```

The command creates:

```text
build/agent-investigation-output/report.json
build/agent-investigation-output/report.md
```

The committed golden reports are in [`demo/investigation/`](demo/investigation/).

## Configure the server

The runtime policy maps symbolic names to operator-approved resources.

Example version 2 policy:

```json
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
```

Start the configured server:

```bash
./build/dev/native-mcp-sandbox --policy-config ./policy.json
```

The server uses newline-delimited JSON-RPC 2.0 over standard input and standard output. It targets MCP revision `2025-11-25`.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the protocol path and [`SECURITY.md`](SECURITY.md) for security expectations.

## Example MCP lifecycle

An unconfigured server supports the MCP lifecycle but advertises no tools:

```bash
./build/dev/native-mcp-sandbox <<'MCP_INPUT'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo-client","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
MCP_INPUT
```

A configured server advertises only the tools enabled by its policy.

## Architecture at a glance

```text
MCP client
    |
    | newline-delimited JSON-RPC 2.0
    v
Protocol parser and lifecycle gate
    |
    +--> bounded JSON preflight
    +--> closed request schemas
    +--> cancellation and deadline context
    v
Fixed two-worker scheduler
    |
    +--> filesystem policy --> logs.search / logs.tail / elf.inspect
    |
    +--> process policy ----> proc.memory
    v
Serialized bounded JSON-RPC responses
```

Core design choices include:

- C++20 with a small coroutine bridge and fixed worker pool;
- no thread-per-request model;
- descriptor-based filesystem containment;
- same-UID and pidfd-backed process observation;
- bounded parsers and explicit output schemas;
- deterministic and coverage-guided adversarial testing;
- native Linux execution with no container requirement.

The design decisions are recorded in [`docs/adr/`](docs/adr/).

## Engineering and assurance

The project is tested across multiple compilers and analysis modes.

| Area | Coverage |
| --- | --- |
| Compilers | GCC Debug and Clang Release |
| Memory safety | AddressSanitizer, UndefinedBehaviorSanitizer, and leak detection |
| Concurrency | Focused ThreadSanitizer scheduler tests |
| Mutation testing | Deterministic mutation runner in normal CTest builds |
| Coverage-guided fuzzing | Five optional Clang libFuzzer targets |
| Integration | Real stdio server execution, strict `openat2`, pidfd, AF_UNIX, and FIFO checks |
| Determinism | Two-run byte equality and committed golden reports |
| Negative behavior | Output flooding, stale reports, malformed protocol input, forbidden report fields, and resource limits |

### Recorded release evidence

For **v0.10.0**:

- all five post-merge GitHub Actions jobs passed;
- the demonstration passed in GCC, Clang, and sanitizer CTest suites;
- the strict demonstration used no legacy compatibility flags;
- deterministic JSON and Markdown reports matched committed golden files;
- output-flood and forbidden-field negative tests passed.
- Phase 9 added bounded reproducibility benchmarks with offline report validation
  and measurement-only comparison groups.

The immutable v0.10.0 tag contained a stale compiled version identifier of
0.9.0. This main-line correction prepares v0.10.1; that tag must not be created
until PR #12 is merged and the exact merge commit passes push-triggered `main`
CI.

For the Phase 7 assurance campaign:

- two deterministic campaigns completed 100,000 iterations each;
- repeated ThreadSanitizer scheduler tests passed;
- strict `openat2`, pidfd, AF_UNIX, and FIFO integration passed;
- five 600-second libFuzzer campaigns executed **61,925,751 inputs** in total;
- those recorded campaigns produced no observed crash, sanitizer finding, timeout, or crash artifact.

These results apply to the tested builds and inputs. They do not prove complete correctness, memory safety, or security.

Detailed evidence is recorded in [`PHASE_8_MANIFEST.md`](PHASE_8_MANIFEST.md), [`PHASE_7_MANIFEST.md`](PHASE_7_MANIFEST.md), and [`docs/FUZZING.md`](docs/FUZZING.md).

## Security boundary

This repository intentionally does **not** provide:

- a shell;
- arbitrary file reads;
- recursive filesystem search;
- filesystem mutation;
- networking;
- raw process memory;
- process maps, command lines, environments, or file descriptors;
- process discovery;
- process control;
- disassembly or malware classification;
- hard real-time cancellation;
- MCP tasks or durable job queues.

Compatibility modes exist for older kernels, but they are explicit opt-ins and have documented limits. Strict mode is the default security target.

Read [`THREAT_MODEL.md`](THREAT_MODEL.md) before extending host authority.

## Repository guide

```text
include/native_mcp/                     Public C++ interfaces
src/                                    Server and policy implementation
tests/                                  Unit, integration, stress, and security tests
fuzz/                                   Corpora, dictionaries, and fuzz targets
scripts/run_agent_investigation_demo.py Deterministic Phase 8 client
demo/investigation/                     Synthetic fixture and golden reports
docs/adr/                               Architecture decision records
ARCHITECTURE.md                         Detailed architecture
SECURITY.md                             Security policy
THREAT_MODEL.md                         Assets, controls, and residual risks
docs/FUZZING.md                         Native fuzzing and triage guide
```

## Project roadmap

- Phases 0–9: complete and released through the immutable `v0.10.0` tag; the
  current main-line correction prepares `v0.10.1`.
- Phase 10: not started; planning follows the separate Phase 9.5 audit.

Each phase is developed as a bounded, reviewable increment. New authority requires an explicit threat-model decision.

## Documentation style

The README is written for developers, reviewers, and recruiters.

Technical specifications and procedures use an ASD-STE100 Issue 9 aligned style. See [`docs/WRITING_STYLE.md`](docs/WRITING_STYLE.md).

## Contributing

Contributions are welcome when they preserve the narrow security boundary and include appropriate tests.

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md). Security-sensitive changes must also follow [`SECURITY.md`](SECURITY.md) and update [`THREAT_MODEL.md`](THREAT_MODEL.md) when assumptions change.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
