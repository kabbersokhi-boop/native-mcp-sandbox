# ADR 0008: Bounded non-executing ELF inspection

- Status: Accepted
- Date: 2026-07-18

## Context

A local investigation can need basic information about an approved Linux binary.
Execution, dynamic loading, and arbitrary mapping would increase the attack surface.
A complete linker-quality parser would exceed the phase boundary.

## Decision

Add `elf.inspect` in Phase 4.
The tool accepts a root name and a relative path.
It obtains one pinned regular-file descriptor through `FilesystemPolicy`.

Use bounded `pread` operations only.
Support ELF32 and ELF64 in both byte orders.
Read selected program-header, dynamic, interpreter, and GNU note metadata.

Check each file range for integer overflow.
Require each range to fit in the captured read budget.
Limit selected metadata reads to 1 MiB.
Use smaller limits for headers, entries, strings, notes, library names, build IDs, and segment summaries.

Do not execute, relocate, dynamically load, shell out to, or memory-map the target.
Report structural hardening indicators only.
Do not report a security verdict.

Primary references:

- `https://man7.org/linux/man-pages/man5/elf.5.html`
- `https://docs.kernel.org/next/ELF/ELF.html`

## Consequences

The project gets a useful binary-inspection tool without a larger host boundary.
The tool does not read sections, symbols, relocations, DWARF, or disassembly.
It does not verify signatures or classify malware.
