# Architecture

## Current system boundary

Phase 2 contains two deliberately separate paths:

1. the Phase 1 MCP protocol server, which exposes no host-access tools; and
2. a filesystem policy library used only by unit tests and future native tools.

The MCP dispatcher is not connected to the policy library. This prevents a partially
reviewed policy from becoming an agent capability merely because the code exists.

## Protocol path

1. Read one bounded line from stdin.
2. Parse one JSON value.
3. Validate JSON-RPC envelope, ID, parameters, and MCP lifecycle.
4. Serialize one bounded response.
5. Write protocol output to stdout and diagnostics to stderr.

## Filesystem policy path

1. Parse a bounded, closed-schema JSON configuration.
2. Validate unique symbolic root names and absolute normalized root paths.
3. Open each root as an owned directory descriptor without following symlinks.
4. Validate an untrusted relative path component by component.
5. Open the target under the selected root with kernel path-resolution restrictions.
6. Inspect the opened descriptor and accept only a bounded regular file.
7. Reopen the pinned inode read-only through `/proc/self/fd` and compare metadata.
8. Return an owned descriptor plus observed and maximum read sizes.

## Strict Linux backend

The strict backend requires `openat2`. Root creation uses no-symlink and no-magic-link
resolution. Target opening additionally uses beneath-root and no-cross-mount
resolution. All fields in `open_how` are zero-initialized before use.

## Compatibility backend

The optional compatibility backend is disabled by default. It walks each path
component using a pinned directory descriptor and `O_PATH | O_NOFOLLOW`. This prevents
textual traversal, symlink following, and rename-based substitution of previously
opened parents. Old kernels do not expose a reliable equivalent of `RESOLVE_NO_XDEV`
for every bind-mount case, so compatibility mode does not claim identical mount
containment.

## Resource invariants

- Configuration text is capped before JSON parsing.
- Root count, root names, path bytes, and per-root file size are bounded.
- Root and target descriptors use RAII and close on every return path.
- Only regular files become readable descriptors.
- The path used for agent-controlled lookup is never passed to a shell.
- File growth after opening does not expand the future read budget.
- stdout remains protocol-only in server mode.

## Planned Phase 3 connection

Phase 3 may introduce a log-analysis tool that receives a root name and relative path,
uses this policy library, and streams at most the returned read budget. It must not
accept raw absolute paths or bypass the policy with conventional `open()` calls.
