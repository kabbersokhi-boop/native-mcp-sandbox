# Threat Model

## Assets

- confidentiality of files outside configured roots;
- confidentiality of denied files and unreturned log or binary bytes;
- integrity of the host filesystem and processes;
- availability of the MCP server and development machine;
- correctness and framing of protocol responses.

## Adversary

The MCP client, tool arguments, root names, paths, queries, ELF bytes, log bytes, file
changes, offsets encoded inside ELF metadata, and request timing are untrusted. The
local operator, installed binary, startup policy configuration, kernel, and compiler
toolchain are trusted for this phase.

## Controls

- bounded closed-schema policy configuration;
- named roots opened as owned descriptors;
- strict `openat2` containment with no symlinks, magic links, or mount crossing;
- explicit weaker legacy mode, disabled by default;
- regular-file and size enforcement with inode revalidation;
- strict relative-path validation;
- fixed captured read budgets;
- bounded log chunks, queries, results, and previews;
- ELF magic, class, byte-order, version, header, table, segment, and string validation;
- overflow-checked ELF offset arithmetic;
- 1 MiB ELF metadata-read ceiling and smaller per-structure limits;
- no execution, `dlopen`, relocation, shell invocation, or target `mmap`;
- escaped binary output and compact schemas;
- closed MCP input schemas and stable tool names;
- tool-call burst limiting;
- 1 MiB protocol message limits;
- stdout isolation and non-echoing stderr diagnostics.

## Denied attacks

Tests cover traversal, absolute paths, root and target symlinks, mount crossing,
directories, FIFOs, sockets, devices, missing and oversized files, malformed numeric
configuration, file growth, chunk-boundary matches, long lines, binary logs, invalid
ELF magic, ELF32/ELF64 byte order, out-of-range tables and segments, extended program
header numbering, oversized metadata budgets, extra tool fields, policy denials, and
rapid repeated calls.

## Residual risks and limitations

- Legacy descriptor walking cannot detect every bind mount.
- A privileged process can modify an already-open file. Phase 4 compares descriptor
  identity, size, modification time, and change time around ELF inspection, but cannot
  make a mutable inode immutable.
- ELF hardening fields are structural indicators, not proof that a binary is safe.
- GNU build IDs are currently read from bounded `PT_NOTE` segments, not section-only
  notes in relocatable files.
- Extended program-header numbering and unusual multiple interpreter or dynamic
  segments are rejected rather than partially interpreted.
- Processing is synchronous and has no hard deadline or cancellation.
- The rate limiter is per process, not an identity-based multi-tenant quota.
- Approved logs and binaries may contain secrets. Operators must configure roots
  narrowly and clients should show tool invocations to users.
- This phase does not add namespaces, Landlock, seccomp, privilege dropping, or a
  network authentication boundary.
