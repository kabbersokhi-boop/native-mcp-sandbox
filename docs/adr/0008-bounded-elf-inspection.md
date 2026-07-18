# ADR 0008: Bounded non-executing ELF inspection

- Status: Accepted
- Date: 2026-07-18

## Context

The next useful agent capability is understanding basic properties of an approved
Linux binary. Executing an untrusted file, loading it with the dynamic linker, or
mapping arbitrary file regions would unnecessarily expand the attack surface. A full
linker-quality ELF implementation would also exceed the phase boundary.

## Decision

Phase 4 adds `elf.inspect`. The tool receives a configured root name and relative path,
then obtains one pinned regular-file descriptor through `FilesystemPolicy`. The
analyzer uses bounded `pread` calls only. It supports ELF32 and ELF64, both byte orders,
and selected program-header, dynamic, interpreter, and GNU note metadata.

Every file range uses overflow-checked arithmetic and must fit inside the policy's
captured read budget. Metadata reads are capped at 1 MiB with narrower limits for
program headers, dynamic entries, strings, notes, library names, build IDs, and returned
segment summaries. The tool never executes, relocates, `dlopen`s, shells out to, or
memory-maps the target.

The tool reports structural hardening indicators, not a security verdict. Unusual
extended numbering, duplicate interpreter or dynamic segments, malformed ranges, and
oversized metadata fail explicitly.

Primary format references:

- https://man7.org/linux/man-pages/man5/elf.5.html
- https://docs.kernel.org/next/ELF/ELF.html

## Consequences

The project gains a useful native binary-inspection capability while preserving the
existing filesystem and resource boundaries. The implementation intentionally omits
sections, symbols, relocations, DWARF, disassembly, signatures, malware classification,
and execution tracing. Those omissions keep Phase 4 reviewable and prevent claims the
code cannot substantiate.
