# Threat model

## Assets

The project protects these assets:

- confidentiality and integrity of host files
- confidentiality and integrity of host processes
- privacy of command lines, environments, maps, descriptors, and memory
- integrity and framing of MCP standard output
- bounded CPU, memory, descriptors, threads, work, JSON, and response size
- operator control of approved roots and processes

## Trusted components

The project trusts these components:

- the installed executable
- the runtime policy file
- the operating system and procfs
- the C++ runtime and compiler toolchain
- the MCP host that starts the server
- the operator-selected roots and process aliases

The project does not trust these inputs:

- MCP client input
- inspected files
- fuzz corpora
- fuzz artifacts
- runtime-policy text before validation

## Untrusted input surfaces

Treat these items as untrusted:

- each byte from standard input
- JSON syntax and structure
- object keys
- method names
- request IDs
- cancellation IDs
- tool arguments
- runtime-policy values
- log data
- ELF data
- procfs data
- process lifetime
- request timing
- request concurrency
- cancellation timing
- EOF timing
- thread-creation and allocation failures

## Controls

The server uses these controls:

- no tools without a runtime policy
- bounded SAX JSON preflight
- duplicate-key rejection
- protocol depth and token limits
- runtime-policy depth and token limits
- closed configuration and tool schemas
- strict filesystem containment
- same-UID process policy
- pidfd pinning in strict process mode
- fixed pseudo-file access
- bounded analyzers
- two fixed worker threads
- at most 16 unfinished calls
- reserved coroutine queue capacity
- duplicate in-flight ID rejection
- canonical non-negative numeric IDs
- steady-clock deadlines
- cooperative stop tokens
- response suppression after client cancellation
- exception-safe worker construction
- serialized shutdown ownership
- one serialized protocol writer
- fixed demonstration request IDs and tool arguments
- canonical reports with stable predicates only
- no raw process memory or process discovery
- compiler, sanitizer, fuzz, race, lifecycle, and integration tests

## Adversarial tests

The deterministic mutation runner and the libFuzzer targets share invariants.
They cover these surfaces:

- protocol input
- runtime-policy input
- log input
- ELF input
- supplied proc-text input

The proc fuzz target does not open host procfs.
It accepts supplied bytes only.

The invariants require these properties:

- bounded output
- valid JSON-RPC output
- exclusive result or error state
- bounded collections
- bounded metadata reads
- bounded previews

Scheduler stress tests these conditions:

- concurrent admission
- queued cancellation
- running cancellation
- cancellation and deadline order
- callback exceptions
- simultaneous shutdown
- partial worker construction

For each confirmed crash, hang, sanitizer report, or race, add a minimized regression.
A finite campaign cannot prove that defects are absent.

## Residual risks

Cancellation is cooperative.
A blocking system call can continue until it returns or reaches a stop check.
The server does not provide hard real-time enforcement.

The unfinished-work limit is process-wide.
It is not a fairness policy for multiple clients.

JSON preflight adds a second parse.
It uses bounded CPU and memory.
It does not replace schema validation.

Duplicate-key tracking uses memory for accepted keys.
The byte and token limits bound this memory.

Responses can finish out of order.
Clients must correlate responses by ID.

Process counters are non-atomic snapshots.
Some `statm` values are approximate.
`smaps_rollup` can be unavailable.

Sanitizers observe executed paths only.
AddressSanitizer and ThreadSanitizer run in separate builds.

Fuzz targets can fail because of host resource exhaustion.
An environmental failure is not automatically a parser defect.

The Phase 8 demonstration uses synthetic data.
It does not claim autonomous response or production suitability.
Its process evidence does not retain runtime counters, PIDs, UIDs, or addresses.

A privileged or compromised kernel can invalidate userspace assumptions.
The legacy filesystem mode cannot detect every bind mount.
The legacy process mode does not have pidfd pinning.

The server does not implement these features:

- MCP tasks
- durable job recovery
- dynamic worker changes
- priorities
- distributed cancellation
