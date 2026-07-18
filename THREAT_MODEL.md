# Threat Model

## Assets

- confidentiality and integrity of host files and processes;
- privacy of process command lines, environments, mappings, and memory contents;
- integrity of MCP protocol output;
- bounded CPU, memory, descriptors, and response size; and
- operator control over which roots and processes are observable.

## Trusted components

- the installed executable and trusted runtime policy file;
- the operating system, procfs implementation, and compiler toolchain;
- the MCP host that launches the process; and
- operator-selected filesystem roots and process aliases.

## Untrusted inputs

- every byte received through stdin;
- JSON structure, methods, IDs, and tool arguments;
- inspected log and ELF contents;
- changing `/proc` pseudo-file contents; and
- target-process lifetime and credential changes after startup.

## Controls

- no-argument mode exposes no host tools;
- closed configuration and tool schemas;
- named filesystem roots and named process aliases;
- strict `openat2` filesystem containment by default;
- same-effective-UID process restriction;
- retained `/proc/<pid>` directory descriptors and recorded start times;
- pidfd lifetime pinning on supported kernels;
- fixed pseudo-file names with no agent-controlled `/proc` paths;
- bounded reads and overflow-checked page conversions;
- no raw memory, mappings, command line, environment, or descriptor enumeration;
- one serialized stdout writer and non-echoing stderr diagnostics; and
- GCC, Clang, ASan, UBSan, malformed-input, lifecycle, and real-process tests.

## Residual risks and limitations

- Aggregate memory values can change while being observed and are snapshots, not a
  transaction across all proc files.
- Linux documents some `statm` values as approximate; `smaps_rollup` is more accurate but
  slower and may be unavailable or permission denied.
- A privileged or compromised kernel can violate userspace assumptions.
- The legacy filesystem backend cannot reliably detect every bind mount.
- The explicit legacy process mode lacks pidfd pinning, although the proc-directory
  descriptor and start time prevent silent PID rebinding in normal kernel behavior.
- The rate limiter is per server process, not a multi-tenant identity quota.
- Processing remains synchronous and has no hard cancellation deadline until Phase 6.
