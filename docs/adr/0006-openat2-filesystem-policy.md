# ADR 0006: Descriptor-based Linux path containment

- Status: Accepted
- Date: 2026-07-18

## Context

Text path normalization is not sufficient for an untrusted path.
A path component can be a symbolic link or a mount point.
A filesystem entry can also change between a check and an open operation.
Phase 2 needs one boundary that later tools cannot bypass.

## Decision

Use named root directory descriptors.
Use Linux `openat2` for strict target resolution.
Accept normalized relative paths only.

Use these strict resolution controls:

- `RESOLVE_BENEATH`
- `RESOLVE_NO_SYMLINKS`
- `RESOLVE_NO_MAGICLINKS`
- `RESOLVE_NO_XDEV`

After resolution, use `fstat` to check the file type and size.
Pin the inode with `O_PATH`.
Open the pinned inode read-only through `/proc/self/fd`.

Stop at startup when `openat2` is not available.
Permit the descriptor-walk backend only with an explicit compatibility option.
The compatibility backend does not claim complete bind-mount detection.

## Consequences

The strict policy is Linux-specific.
It requires Linux 5.6 or newer and an available procfs.
The code is longer than a `std::filesystem::canonical` solution.
It gives a reviewable boundary against traversal, symbolic-link, and rename races.
