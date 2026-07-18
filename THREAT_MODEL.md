# Threat Model

## Protected assets

- files outside explicitly configured roots;
- files reached through symbolic, magic-link, traversal, or mount escapes;
- device nodes, sockets, FIFOs, directories, and other special targets;
- host memory and CPU availability;
- protocol framing and stdout integrity; and
- configuration and diagnostic privacy.

## Adversary capabilities

An untrusted client may provide malformed JSON-RPC, invalid lifecycle sequences,
oversized lines, hostile root names or relative paths to future tools, repeated
requests, and paths that race with filesystem changes. A local untrusted user may
rename entries, replace them with symlinks, grow files, or create special files under
an otherwise approved directory.

## Phase 2 controls

- Host access is still unreachable through MCP.
- Configuration parsing uses a closed schema and bounded input.
- Roots are named, explicit, read-only, and opened as descriptors.
- Relative paths reject absolute, empty, dot, parent, and repeated-separator forms.
- Strict target resolution stays beneath the root and denies symlinks, magic links,
  and mount crossings.
- Descriptor checks accept only regular files within a configured size limit.
- The checked inode is pinned before obtaining the readable descriptor.
- The compatibility backend is opt-in and documented as weaker for bind mounts.
- Protocol request and response limits remain enforced.

## Residual risks and explicit limitations

- Phase 2 does not expose an MCP analysis tool, so it does not yet prove end-to-end
  agent authorization.
- A regular file can grow after opening; future readers must enforce the stored maximum
  byte budget rather than trust a stale size.
- Strict mode depends on Linux `openat2`; old kernels fail closed unless compatibility
  mode is explicitly enabled.
- Reopening a pinned descriptor depends on procfs and normal read permissions.
- The project does not yet use namespaces, Landlock, seccomp, privilege dropping, or a
  separate broker process.
- Hard links inside an approved root refer to the linked inode and are considered part
  of the root's approved namespace.
- Denial-of-service from many sequential valid requests remains bounded by the current
  synchronous server but deadlines and cancellation arrive in later phases.

## Security non-goals

This project does not claim to contain arbitrary code execution, safely run untrusted
binaries, prevent a privileged local administrator from interfering, or provide a
complete operating-system sandbox.
