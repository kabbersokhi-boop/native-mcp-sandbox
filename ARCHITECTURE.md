# Architecture

## System boundary

Release `v0.8.0` provides four read-only MCP tools.
The server enables a tool only when the operator supplies a trusted runtime policy.

The tools are:

- `logs.search`
- `logs.tail`
- `elf.inspect`
- `proc.memory`

The server exposes no tools when it has no runtime policy.
The server does not add these capabilities:

- filesystem changes
- process control
- raw process memory
- shell execution
- networking
- MCP tasks

Phase 8 will add a demonstration client.
The client will use the existing tools only.
It will not change the server boundary.

## Protocol path

The server processes a request in this sequence:

1. The main thread reads one size-limited JSON-RPC line from standard input.
2. The SAX preflight checks JSON syntax, duplicate keys, depth, and token count.
3. The reader checks the MCP lifecycle and the closed request schema.
4. The reader writes immediate protocol and discovery responses.
5. A valid `tools/call` reserves one slot in the unfinished-work set.
6. A C++20 coroutine suspends and puts its handle in reserved queue storage.
7. One worker resumes the coroutine.
8. The selected tool uses the applicable policy gate.
9. The analyzer checks cancellation and the deadline at bounded points.
10. The serialized writer writes one complete response line.

A tool response can finish before an earlier tool response.
The JSON-RPC ID identifies the applicable request.
Worker threads do not change the MCP lifecycle state.

## JSON preflight

`preflight_json` uses the nlohmann/json SAX interface.
It does not construct a DOM.

The preflight counts these items:

- scalar values
- arrays
- objects
- object keys

It keeps object keys only until the applicable object closes.
It rejects a duplicate key in the same object.

Protocol JSON has these limits:

- 64 nested containers
- 32,768 tokens
- 1 MiB of input

Runtime-policy JSON has these limits:

- 32 nested containers
- 4,096 tokens
- 64 KiB of input

The normal DOM parser runs after the preflight.
Closed schema validation runs after DOM construction.
This double parse uses bounded CPU to reduce ambiguity and resource risk.

## Work control

The scheduler has these fixed limits:

- 16 unfinished tool calls
- two worker threads
- a 30-second deadline for each accepted call
- 16 submissions in one second
- 1 MiB for each request and response

The unfinished-work limit includes queued and running work.
The server returns `server_busy` when the limit is full.
The server rejects a duplicate in-flight request ID.

The scheduler uses one canonical key for equal non-negative signed and unsigned numeric IDs.
A string ID stays different from a numeric ID.

The scheduler reserves queue capacity during construction.
A suspension callback does not allocate queue storage.
The server does not create one thread for each request.

Worker construction is exception-safe.
If worker creation fails, the constructor stops and joins each worker that already started.
Then the constructor propagates the exception.

A worker callback can request shutdown.
This request closes admission and returns without a wait or a join.
A non-worker shutdown drains accepted work and joins all workers.
The join operation has one owner.

## Cancellation and deadlines

The server accepts `notifications/cancelled` only as a notification.
The notification must contain a valid `requestId`.

For matching work, the server does these actions:

- It requests stop through `std::stop_source`.
- It suppresses the normal tool response.
- It lets the analyzer stop at its next bounded check.

The server ignores an unknown or completed request ID.

Deadlines use `std::chrono::steady_clock`.
The server returns `deadline_exceeded` when work expires.
A prior client cancellation keeps response suppression in control.

Cancellation is cooperative.
The server does not forcibly terminate a worker.
It does not claim hard real-time interruption of an arbitrary system call.

## Filesystem boundary

Filesystem tools accept a root name and a relative path.
The client cannot supply an absolute path.

Strict mode uses `openat2` with these controls:

- `RESOLVE_BENEATH`
- `RESOLVE_NO_SYMLINKS`
- `RESOLVE_NO_MAGICLINKS`
- `RESOLVE_NO_XDEV`

The policy checks the file type, access mode, and size.
It keeps the accepted inode through an owned descriptor.

The compatibility descriptor walk is an explicit option.
It cannot detect every bind-mount boundary.

## Process boundary

The operator configures each process target.
The MCP client selects a process name only.
The client cannot supply a raw PID.

The policy requires the same effective UID.
It keeps the `/proc/<pid>` directory descriptor.
It records process start time.
Strict mode also requires a pidfd.

The tool reads only bounded aggregate data from these files:

- `status`
- `statm`
- optional `smaps_rollup`

The tool does not read process memory, maps, command lines, environments, or file descriptors.
It verifies process identity before and after an observation.

## Output and shutdown

EOF stops new admission.
The server drains accepted work before it joins workers.

One mutex protects the protocol writer.
Standard output contains complete JSON-RPC lines only.
Standard error contains generic diagnostics.
Diagnostics do not echo request, file, or process data.

## Assurance design

`native_mcp_fuzz_support` contains shared invariants for these surfaces:

- protocol and JSON safety
- runtime-policy parsing
- ELF analysis
- log analysis
- bounded proc-text parsing

The deterministic mutation runner uses these invariants in normal CTest builds.
The optional Clang libFuzzer targets use the same invariants.
The proc parser fuzz target accepts supplied bytes only.
It does not open host procfs.

Curated corpora and dictionaries are in `fuzz/`.
Generated artifacts stay under `build/` until review and minimization.

Concurrency tests are separate from byte fuzzing.
They test admission, cancellation, deadlines, callback failures, and shutdown races.
A focused ThreadSanitizer build runs these tests.

The project runs directly on Linux.
It does not require a container runtime.

## Recorded Phase 7 evidence

Phase 7 assurance used Ubuntu 24.04.
It tested source head `df576168fd44561254736a60c45188333bd1bc50`.

The tests included:

- two deterministic campaigns with 100,000 iterations each
- 50 ThreadSanitizer unit repetitions
- 25 ThreadSanitizer stress repetitions
- strict `openat2` and pidfd checks
- 50 AF_UNIX and FIFO policy repetitions
- 20 configured standard-I/O integration repetitions
- five libFuzzer campaigns of 600 seconds each

The libFuzzer campaigns executed 61,925,751 inputs.
The runs found no crash, sanitizer finding, timeout, or crash artifact.
This evidence applies to the tested build and inputs only.
It is not proof of complete correctness or security.
