# Native MCP Sandbox

> A security-first C++20 server for bounded, read-only Linux evidence tools.

Native MCP Sandbox gives an MCP client access to selected Linux evidence.
The server does not provide a shell or an unrestricted file browser.
The server does not read raw process memory.

## Project status

Release `v0.8.0` is complete.
Phase 8 is in development.
Phase 8 will add a deterministic investigation demonstration.
It will not add a new MCP tool or new host authority.

The server exposes no tools when you start it without a runtime policy.
A trusted runtime policy can enable these tools:

- `logs.search` searches one approved regular file for literal text.
- `logs.tail` returns previews of the final lines in one approved regular file.
- `elf.inspect` reads selected metadata from one approved ELF file.
- `proc.memory` reads aggregate memory counters for one named same-UID process.

The MCP client selects an operator-defined root name or process name.
The client cannot supply an absolute target path or a raw PID.

## Runtime policy

Use schema version 1 for filesystem tools only:

```json
{
  "version": 1,
  "roots": [
    {
      "name": "evidence",
      "path": "/srv/approved-evidence",
      "maxFileBytes": 16777216
    }
  ]
}
```

Use schema version 2 for filesystem tools, process tools, or both:

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
    },
    {
      "name": "worker",
      "pid": 12345
    }
  ]
}
```

At least one capability must be present.
Each root name and process name must be unique.

Start the configured server:

```bash
./build/dev/native-mcp-sandbox --policy-config ./policy.json
```

Strict mode requires Linux `openat2` for filesystem targets.
Strict process mode also requires `pidfd_open`.
The server stops at startup when a required strict feature is not available.

Use a compatibility mode only when you accept its limits:

```bash
./build/dev/native-mcp-sandbox \
  --policy-config ./policy.json \
  --allow-legacy-descriptor-walk \
  --allow-legacy-process-pinning
```

The server writes a warning to standard error for each compatibility mode.
The legacy filesystem mode cannot detect every bind-mount boundary.
The legacy process mode does not provide pidfd-backed lifetime pinning.

## Filesystem tools

The filesystem policy uses directory descriptors.
Strict mode uses these `openat2` controls:

- `RESOLVE_BENEATH`
- `RESOLVE_NO_SYMLINKS`
- `RESOLVE_NO_MAGICLINKS`
- `RESOLVE_NO_XDEV`

The policy accepts only bounded regular files.
The policy opens each accepted file through a pinned descriptor.

### `logs.search`

Required arguments:

- `root`
- `path`
- `query`

The query length is from 1 through 256 bytes.
The optional `caseSensitive` value is `true` by default.
A `false` value folds ASCII letters only.
The optional `maxMatches` value is from 1 through 50.
Its default value is 20.

The analyzer reads the file in 8 KiB chunks.
A match can cross a chunk boundary.
The analyzer does not load the complete file.

### `logs.tail`

Required arguments:

- `root`
- `path`

The optional `maxLines` value is from 1 through 50.
Its default value is 20.
The analyzer keeps only the requested final previews.
The result identifies a preview that does not contain the start of a long line.

### `elf.inspect`

Required arguments:

- `root`
- `path`

The analyzer does not execute, load, relocate, or memory-map the target.
It uses bounded `pread` operations.
It supports selected ELF32 and ELF64 metadata.
The result can include these items:

- ELF identity
- interpreter
- needed libraries
- GNU build ID
- bounded segment summaries
- stack policy
- RELRO status
- PIE-like status
- writable and executable load-segment status

These items are structural observations.
They are not a malware verdict or a safety verdict.

## Process tool

### `proc.memory`

Required input:

```json
{"process":"server"}
```

The process name must be in the trusted runtime policy.
At startup, the server does these actions:

1. It verifies that the target has the same effective UID.
2. It opens and keeps `/proc/<pid>` as a directory descriptor.
3. It records field 22 from `/proc/<pid>/stat`.
4. It obtains a pidfd in strict mode.

The server verifies process identity before and after each observation.
The tool returns an error when the process exits or its identity changes.

The tool reads only these pseudo-files:

- `status`
- `statm`
- optional `smaps_rollup`

The tool does not read these interfaces:

- `/proc/<pid>/mem`
- `maps`
- `smaps`
- `pagemap`
- `cmdline`
- `environ`
- `fd`

The counters are non-atomic snapshots.
Some `statm` values are approximate.
The result reports when `smaps_rollup` is not available.
The tool does not use a more invasive fallback.

## Work control

The server uses two worker threads.
The server accepts at most 16 unfinished tool calls.
This limit includes queued and running calls.

The server returns `server_busy` when the limit is full.
The server returns `duplicate_request_id` for a duplicate in-flight ID.
Equal non-negative signed and unsigned numeric IDs have one internal identity.
String IDs stay different from numeric IDs.

Each accepted call has a 30-second steady-clock deadline.
The server supports MCP `notifications/cancelled` for in-flight tool calls.
Cancellation is cooperative.
The analyzers check for cancellation at bounded points.
The server does not forcibly terminate a worker thread.

Tool responses can finish in a different order from requests.
The client must use the JSON-RPC ID to correlate each response.
One serialized writer writes complete response lines to standard output.

A worker callback can request shutdown.
This request stops new admission and returns without a wait or a join.
A later non-worker shutdown drains accepted work and joins all workers.
EOF also stops admission and drains accepted work.

## JSON safety

The server runs a SAX preflight before it constructs a JSON DOM.
The preflight checks these conditions:

- valid JSON syntax
- no duplicate object keys
- bounded container depth
- bounded token count

Protocol JSON permits at most 64 nested containers and 32,768 tokens.
Runtime-policy JSON permits at most 32 nested containers and 4,096 tokens.
The protocol byte limit is 1 MiB.
The runtime-policy byte limit is 64 KiB.
Closed schema validation runs after the preflight.

## Fixed limits

| Boundary | Limit |
| --- | ---: |
| Runtime policy text | 64 KiB |
| Protocol JSON nesting | 64 containers |
| Protocol JSON tokens | 32,768 |
| Runtime-policy JSON nesting | 32 containers |
| Runtime-policy JSON tokens | 4,096 |
| Filesystem roots | 16 |
| Process aliases | 16 |
| Process `stat` read | 8 KiB |
| Process `status` read | 64 KiB |
| Process `statm` read | 4 KiB |
| Process `smaps_rollup` read | 256 KiB |
| Log scan | 16 MiB |
| Log read chunk | 8 KiB |
| Log preview source bytes | 512 per returned line |
| Search matches or tail lines | 50 |
| ELF selected metadata reads | 1 MiB |
| ELF program headers | 256 |
| ELF dynamic entries | 4,096 |
| ELF dynamic string table | 256 KiB |
| Unfinished tool calls | 16 |
| Worker threads | 2 |
| Tool-call deadline | 30 seconds |
| Tool-call burst | 16 calls in one second |
| JSON-RPC request | 1 MiB |
| JSON-RPC response | 1 MiB |

## MCP behavior

The server uses MCP revision `2025-11-25`.
It uses newline-delimited JSON-RPC 2.0 on standard input and standard output.

The server supports these methods:

- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list`
- `tools/call` when a policy enables tools
- `notifications/cancelled` for in-flight tool calls

Tool schemas are closed.
Tool annotations identify read-only behavior.
MCP task support is forbidden.

Successful tool calls return equal `structuredContent` and text content.
Expected tool failures use `isError`.
Protocol errors use JSON-RPC error objects.

Standard output contains protocol messages only.
Standard error contains generic diagnostics and compatibility warnings.
Diagnostics do not echo request data, file data, or process data.

## Unconfigured example

```bash
./build/dev/native-mcp-sandbox <<'MCP_INPUT'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo-client","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"ping"}
{"jsonrpc":"2.0","id":3,"method":"tools/list"}
MCP_INPUT
```

Expected standard output:

```jsonl
{"id":1,"jsonrpc":"2.0","result":{"capabilities":{"tools":{}},"protocolVersion":"2025-11-25","serverInfo":{"name":"native-mcp-sandbox","version":"0.8.0"}}}
{"id":2,"jsonrpc":"2.0","result":{}}
{"id":3,"jsonrpc":"2.0","result":{"tools":[]}}
```

The initialized notification has no response.
The normal transcript writes nothing to standard error.

## Build and test

Requirements:

- Linux
- CMake 3.20 or newer
- Ninja
- a C++20 GCC or Clang compiler
- nlohmann/json 3.11 or newer
- Linux `openat2` and ELF headers
- procfs
- pidfd support for strict process mode

The project does not use a libelf or procps runtime dependency.

Run the normal builds:

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev

cmake --preset release
cmake --build --preset release
ctest --preset release
```

Run the sanitizer build:

```bash
cmake --preset sanitizers
cmake --build --preset sanitizers
ASAN_OPTIONS=detect_leaks=1 ctest --preset sanitizers
```

Run the focused ThreadSanitizer tests:

```bash
CXX=g++ cmake --preset thread-sanitizer
cmake --build --preset thread-sanitizer
TSAN_OPTIONS=halt_on_error=1 \
  ctest --preset thread-sanitizer -R '^orchestration\.(unit|stress)$'
```

Build the optional fuzz targets:

```bash
CXX=clang++ cmake --preset fuzzers
cmake --build --preset fuzzers
```

Run the native stress and fuzz scripts:

```bash
NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh
NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh
```

The scripts use at most two compilation jobs.
The project does not require a container runtime.

## Phase 7 assurance evidence

Phase 7 assurance used Ubuntu 24.04.
It tested source head `df576168fd44561254736a60c45188333bd1bc50`.

The assurance work completed these tests:

- two deterministic campaigns with 100,000 iterations each
- repeated ThreadSanitizer scheduler tests
- strict `openat2` and pidfd integration
- real AF_UNIX and FIFO integration
- five parallel libFuzzer campaigns of 600 seconds each

The five libFuzzer campaigns executed 61,925,751 inputs.
The recorded runs found no crash, sanitizer finding, timeout, or crash artifact.
These results apply only to the tested build and inputs.
They do not prove complete correctness or security.

## Limitations

The server does not provide these capabilities:

- regular-expression search
- recursive search
- file watching
- arbitrary file reads
- filesystem changes
- shell execution
- networking
- ELF sections or symbols
- disassembly
- signature verification
- raw process memory
- process maps
- process command lines
- process environments
- process discovery
- forced cancellation
- hard real-time preemption
- MCP tasks
- dynamic worker changes
- priorities
- durable queues

Fuzzing has finite time and finite input coverage.
A clean fuzzing run is not proof of memory safety or correctness.

## Roadmap

1. Phase 0: foundation, limits, build, tests, and CI — complete.
2. Phase 1: minimal MCP lifecycle and JSON-RPC over standard I/O — complete.
3. Phase 2: filesystem policy and resource control — complete.
4. Phase 3: streaming log tools — complete.
5. Phase 4: bounded Linux ELF inspection — complete.
6. Phase 5: bounded `/proc` memory observation — complete.
7. Phase 6: coroutine orchestration, cancellation, and backpressure — complete.
8. Phase 7: fuzzing, sanitizers, and security regressions — complete.
9. Phase 8: deterministic agent investigation demonstration — in development.
10. Phase 9: reproducible benchmarks and reference comparison — not started.
11. Phase 10: release hardening and stable tool interface — not started.

## Main files

```text
include/native_mcp/json_safety.hpp          Bounded JSON preflight API
src/json_safety.cpp                         JSON syntax, depth, token, and duplicate-key checks
fuzz/fuzz_support.cpp                       Shared fuzz invariants
fuzz/fuzz_smoke.cpp                         Deterministic mutation runner
fuzz/fuzz_*.cpp                             Optional Clang libFuzzer targets
fuzz/corpus/                                Curated regression inputs
scripts/run_fuzz_campaign.sh                Timed native fuzz campaigns
scripts/run_security_stress.sh              Sanitizer, deterministic, and TSan tests
docs/FUZZING.md                             Fuzz campaign and triage instructions
tests/security_regression_tests.cpp         Security regression tests
tests/orchestration_stress_tests.cpp        Scheduler stress tests
include/native_mcp/orchestration.hpp        Scheduler API
src/orchestration.cpp                       Worker pool and work control
include/native_mcp/operation.hpp            Stop and deadline context
include/native_mcp/runtime_config.hpp       Runtime-policy parser API
src/runtime_config.cpp                      Runtime-policy parser
include/native_mcp/process_memory.hpp       Process-memory API
include/native_mcp/process_parsing.hpp      Bounded proc-text parser API
src/process_memory.cpp                      Process policy and proc reads
include/native_mcp/file_policy.hpp          Filesystem policy API
src/file_policy.cpp                         Filesystem containment
include/native_mcp/log_analysis.hpp         Log-analysis API
src/log_analysis.cpp                        Log search and tail
include/native_mcp/elf_analysis.hpp         ELF-analysis API
src/elf_analysis.cpp                        ELF metadata analysis
```

## Documentation style

The active technical documents use an ASD-STE100 Issue 9 aligned style.
See [`docs/WRITING_STYLE.md`](docs/WRITING_STYLE.md).

## License

Apache License 2.0.
See [`LICENSE`](LICENSE).
