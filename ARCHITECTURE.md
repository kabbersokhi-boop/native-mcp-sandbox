# Architecture

## Current boundary

Phase 4 exposes three narrow MCP tools only when the operator supplies a trusted
filesystem policy at startup:

- `logs.search` — bounded literal matching in one approved regular file;
- `logs.tail` — bounded previews of final logical lines; and
- `elf.inspect` — bounded structural inspection of one approved ELF file.

With no policy configuration, the server remains host-isolated and advertises no
tools. No tool accepts an absolute target path or opens a file outside the reviewed
filesystem policy.

## Data path

1. Read one bounded JSON-RPC line from stdin.
2. Validate the MCP lifecycle and closed tool-call envelope.
3. Apply the per-process tool-call burst limiter.
4. Resolve a symbolic root and relative path through `FilesystemPolicy`.
5. Pin and revalidate a bounded regular-file descriptor.
6. Dispatch either the streaming log analyzer or the bounded ELF metadata reader.
7. Produce compact structured evidence that conforms to the advertised output schema.
8. Serialize one bounded response through the single stdout writer.

## Components

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Stdio server | Frame JSON-RPC and enforce lifecycle | Write diagnostics to stdout |
| Tool service | Validate calls, advertise schemas, rate-limit bursts | Accept undeclared tools or fields |
| Filesystem policy | Resolve named-root relative paths | Follow symlinks or return special files |
| Log analyzer | Literal search and bounded tail | Load the whole file or execute contents |
| ELF analyzer | Parse bounded ELF metadata with `pread` | Execute, load, relocate, or memory-map the target |
| Result serializer | Return compact MCP evidence | Exceed the response budget |

## ELF inspection

`elf.inspect` supports ELF32 and ELF64 files in little- or big-endian form. It reads
only the identification bytes, ELF header, bounded program headers, selected dynamic
metadata, interpreter, GNU build-ID notes, and bounded string data. Every addition and
multiplication used for a file range is overflow-checked and the final range must fit
inside the read budget captured by the policy gate.

The analyzer reports identity, entry point, program segments, interpreter, needed
libraries, GNU build ID when present in a `PT_NOTE`, and common hardening signals:

- executable-stack policy from the last `PT_GNU_STACK` segment;
- RELRO presence plus immediate binding for a `none`/`partial`/`full` summary;
- writable-and-executable load segments; and
- position-independent and PIE-like executable indicators.

These are bounded structural observations, not a vulnerability verdict. Extended
program-header numbering, multiple interpreter or dynamic segments, and metadata that
exceeds configured limits fail explicitly rather than being guessed.

## Resource invariants

- Log scans are capped at 16 MiB and use 8 KiB chunks.
- ELF inspection reads at most 1 MiB of selected metadata.
- Program headers are capped at 256; dynamic entries at 4096.
- Dynamic strings are capped at 256 KiB; needed libraries at 64.
- Note data is capped at 256 KiB; build IDs at 64 bytes.
- At most 64 segment summaries are returned.
- Tool calls are limited to a burst of 16 per one-second window.
- Protocol requests and responses remain capped at 1 MiB.
- stdout has one logical writer.

## Error model

Malformed MCP calls and unknown tool names are JSON-RPC errors. Expected policy,
argument, parse, read, unsupported-feature, and rate-limit failures are MCP tool
execution errors with `isError`. Successful structured results conform to advertised
output schemas. Execution errors omit `structuredContent` because those schemas
describe successful output.

## Concurrency

Phase 4 remains synchronous. There is no worker pool, coroutine scheduling,
cancellation, or hard operation deadline. Bounded file and metadata limits constrain
individual work; full scheduling and backpressure remain a later phase.
