# ADR 0006: Use descriptor-based Linux path containment

- Status: accepted
- Date: 2026-07-18

## Context

Textual canonicalization is not sufficient for untrusted paths because filesystem
entries can be symbolic links, mount points, or can change between a check and an
open. Phase 2 needs a boundary that future tools cannot accidentally bypass.

## Decision

Use named root directory descriptors and Linux `openat2` for strict target resolution.
Requests must be normalized relative paths. Strict opens use `RESOLVE_BENEATH`,
`RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS`, and `RESOLVE_NO_XDEV`, followed by
`fstat` regular-file and size checks. The inode is pinned with `O_PATH` before it is
reopened read-only through `/proc/self/fd`.

Kernels without `openat2` fail closed by default. An explicit compatibility option may
walk path components with descriptor-relative `openat` and `O_NOFOLLOW`; it does not
claim complete same-filesystem bind-mount detection.

## Consequences

The strong policy is Linux-specific and requires Linux 5.6 or newer. procfs must be
available to obtain a readable descriptor from the pinned inode. The approach is more
verbose than `std::filesystem::canonical`, but it provides a reviewable boundary
against traversal, symlink, and rename races.
