# Threat Model

## Assets

- confidentiality of files outside configured roots;
- confidentiality of denied files and unreturned log bytes;
- integrity of the host filesystem and processes;
- availability of the MCP server and development machine;
- correctness and framing of protocol responses.

## Adversary

The MCP client, tool arguments, root names, paths, query text, file contents, file
growth, and request timing are untrusted. The local operator, installed binary, startup
policy configuration, kernel, and compiler toolchain are trusted for this phase.

## Controls

- bounded closed-schema policy configuration;
- named roots opened as owned descriptors;
- strict `openat2` containment with no symlinks, magic links, or mount crossing;
- explicit weaker legacy mode, disabled by default;
- regular-file and size enforcement with inode revalidation;
- strict relative-path validation;
- fixed observed-size read budget;
- 16 MiB synchronous scan ceiling;
- bounded queries, chunks, matches, tail lines, and previews;
- escaping of binary and non-printable output bytes;
- closed MCP input schemas and stable tool names;
- tool-call burst limiting;
- 1 MiB protocol message limits;
- stdout isolation and non-echoing stderr diagnostics.

## Denied attacks

Tests cover traversal, absolute paths, root and target symlinks, mount crossing,
directories, FIFOs, sockets, devices, missing and oversized files, malformed numeric
configuration, file growth after opening, chunk-boundary matches, long lines, binary
content, extra tool fields, invalid limits, and rapid repeated calls.

## Residual risks and limitations

- Legacy descriptor walking cannot detect every bind mount.
- A privileged process can modify an already-open file; growth is excluded from the
  read budget, but same-size content changes are not prevented.
- Reading up to 16 MiB is synchronous and has no hard deadline or cancellation.
- The rate limiter is per process and is not an identity-based multi-tenant quota.
- Logs may contain secrets. Operators must configure roots narrowly and clients should
  show tool invocations to users.
- This phase does not add namespaces, Landlock, seccomp, privilege dropping, or a
  network authentication boundary.
