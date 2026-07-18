# Architecture

## Purpose

Native MCP Sandbox will mediate between a local MCP client and a small collection
of read-only Linux analysis tools. It is designed around explicit trust boundaries,
bounded resource use, deterministic protocol output, and compact context returned to
an AI model.

Phase 0 contains only the foundation types and executable self-check. Sections that
describe future components are marked **planned**.

## System boundaries

### Trusted for the initial model

- the locally installed server executable and its configuration;
- the operating system and compiler toolchain;
- the human-selected analysis roots; and
- the MCP host that launches the process.

### Untrusted

- every byte received through standard input;
- file names and tool arguments supplied by an agent;
- contents of inspected logs and binaries;
- process identifiers supplied in requests; and
- client behavior, including cancellation and abrupt disconnection.

## Planned components

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Standard-I/O transport | Frame and emit protocol messages | Write diagnostics to stdout |
| JSON-RPC dispatcher | Validate envelopes and route methods | Perform filesystem work directly |
| MCP lifecycle | Initialize, list tools, call tools, shut down | Advertise unavailable capabilities |
| Policy gate | Authorize paths, operations, sizes, and PIDs | Infer permission from user intent |
| Resource governor | Bound queues, outputs, workers, and time | Allocate without configured limits |
| Analysis tools | Stream and reduce approved evidence | Execute inspected data |
| Response serializer | Produce one complete response at a time | Interleave output from workers |
| Diagnostic logger | Record operational events to stderr | Include secrets or arbitrary file contents |

## Concurrency model

The planned server will have one protocol reader, one serialized protocol writer,
and a small bounded worker pool. C++20 coroutines will express operations that wait
for input, timers, or worker completion. Expensive file analysis will not run on the
protocol thread.

The worker pool is limited to two threads by default. A bounded queue provides
backpressure. Cancellation is cooperative and every long-running tool must check a
cancellation signal at defined intervals.

## Resource invariants

The following properties are established as design invariants:

1. A request is rejected before unbounded buffering.
2. A response cannot exceed its configured byte budget.
3. The pending-work queue has a fixed maximum capacity.
4. Worker count is fixed during normal operation.
5. Every analysis operation has a deadline.
6. Large files are processed incrementally.
7. Standard output has exactly one logical writer.
8. Tools are read-only unless a future threat-model revision explicitly says otherwise.

Phase 0 implements and tests validation for the default resource-budget object. It
does not yet enforce these invariants against protocol traffic.

## Dependency policy

Dependencies will be introduced only with a written architecture decision that
explains why the standard library is insufficient, how the dependency is pinned,
and how security updates will be handled. The expected Phase 1 candidates are a
maintained JSON library and Boost.Asio. Neither is a Phase 0 dependency.

## Portability

The transport and policy layers should remain portable where practical, but log,
ELF, `/proc`, namespace, and seccomp functionality is Linux-specific. Linux is the
only promised target until automated tests prove otherwise.
