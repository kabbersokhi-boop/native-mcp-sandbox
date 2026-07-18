# Native MCP Sandbox

> A security-first, resource-bounded C++20 server for local AI-agent evidence tools.

Native MCP Sandbox gives an MCP client narrow, read-only access to selected
Linux evidence without exposing a shell or unrestricted filesystem browser. The project
is built in small auditable phases: protocol handling, filesystem containment, then
bounded analysis tools.

## Project status

**Phase 3 — Streaming log-analysis tools (`v0.4.0`)**

With no arguments, the executable remains a host-isolated MCP lifecycle server and
advertises no tools. When started with a trusted policy configuration, it exposes two
read-only tools:

- `logs.search` — literal byte-sequence search in one approved regular file;
- `logs.tail` — bounded previews of the final logical lines in one approved file.

Both tools open files only through the Phase 2 descriptor-based policy gate. They do
not accept absolute target paths, execute shell commands, use the network, mutate
files, or follow symbolic links.

## Security boundary

An operator starts the server with a bounded policy file:

```json
{
  "version": 1,
  "roots": [
    {
      "name": "application-logs",
      "path": "/var/log/my-application",
      "maxFileBytes": 16777216
    }
  ]
}
```

Start the configured server:

```bash
./build/dev/native-mcp-sandbox --policy-config ./policy.json
```

Strict mode requires Linux `openat2`. It resolves targets beneath a pinned root with
`RESOLVE_BENEATH`, `RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS`, and
`RESOLVE_NO_XDEV`. Only regular files within the configured size limit become readable.
The checked inode is reopened through `/proc/self/fd` and revalidated before use.

On an older kernel, startup fails closed. `--allow-legacy-descriptor-walk` is an
explicit compatibility option for controlled environments. It still rejects traversal
and symlinks using pinned directory descriptors, but it cannot prove every bind-mount
boundary and prints a warning to stderr.

The policy configuration is trusted operator input. Tool arguments remain untrusted.

## Phase 3 tools

### `logs.search`

Required arguments are `root`, `path`, and a nonempty literal `query` of at most 256
bytes. Optional `caseSensitive` defaults to `true`; `false` folds ASCII letters only.
Optional `maxMatches` is 1–50 and defaults to 20.

The implementation uses streaming Knuth–Morris–Pratt matching, so a match may cross an
8 KiB read boundary without loading the full file. At most one result is returned per matching line, using the first occurrence. Each result contains a one-based
line number, absolute byte offset, bounded escaped preview, and truncation flags.

### `logs.tail`

Required arguments are `root` and `path`. Optional `maxLines` is 1–50 and defaults to
20. The implementation scans incrementally and retains only the requested final
bounded previews. Very long lines retain their end and report that the beginning was
truncated.

### Fixed limits

- synchronous scan size: 16 MiB;
- read chunk: 8 KiB;
- preview source bytes per returned line: 512;
- search query: 256 bytes;
- search matches: 50;
- tail lines: 50;
- tool-call burst: 16 calls per one-second window;
- JSON-RPC request and response: 1 MiB each.

File size is captured when the policy opens the descriptor. Growth after that point
does not expand the read budget, and a detected size change is disclosed in the result.
Non-printable and non-ASCII bytes are rendered as `\xHH` in previews so results remain
compact valid JSON.

## MCP behavior

The server targets MCP revision `2025-11-25` over newline-delimited JSON-RPC 2.0 on
stdin/stdout. It supports `initialize`, `notifications/initialized`, `ping`,
`tools/list`, and—only in configured mode—`tools/call`.

Tool definitions include closed input schemas, success output schemas, read-only
annotations, and synchronous task metadata. Successful calls return matching
`structuredContent` and serialized text content. Tool execution errors use `isError`
and text content without claiming conformance to the success output schema. Unknown
tools and malformed call envelopes are protocol errors.

Stdout contains only complete protocol messages. Generic diagnostics and the explicit
legacy-mode warning go to stderr without echoing request or log contents.

## Reproducible unconfigured transcript

```bash
./build/dev/native-mcp-sandbox <<'MCP_INPUT'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo-client","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"ping"}
{"jsonrpc":"2.0","id":3,"method":"tools/list"}
MCP_INPUT
```

Expected stdout:

```jsonl
{"id":1,"jsonrpc":"2.0","result":{"capabilities":{"tools":{}},"protocolVersion":"2025-11-25","serverInfo":{"name":"native-mcp-sandbox","version":"0.4.0"}}}
{"id":2,"jsonrpc":"2.0","result":{}}
{"id":3,"jsonrpc":"2.0","result":{"tools":[]}}
```

The initialized notification receives no response, and this normal transcript writes
nothing to stderr. The process integration test compares this output exactly and also
launches a configured server to call both Phase 3 tools.

## Build and verify

Requirements: Linux, CMake 3.20+, Ninja, a C++20 GCC or Clang compiler,
system-provided nlohmann/json 3.11+, and Linux headers providing `openat2`.
On EndeavourOS or Arch Linux, install `nlohmann-json`; CMake does not fetch dependencies.

```bash
cmake --preset dev -DNMS_WARNINGS_AS_ERRORS=ON
cmake --build --preset dev
ctest --preset dev

cmake --preset sanitizers
cmake --build --preset sanitizers
ctest --preset sanitizers
```

Presets use at most two compilation jobs. Docker and a local language model are not
required.

## Architecture

```mermaid
flowchart LR
    A["MCP client"] --> B["bounded stdio and lifecycle"]
    B --> C["closed schemas and rate limit"]
    C --> D["filesystem policy gate"]
    D --> E["pinned regular-file descriptor"]
    E --> F["streaming literal search or tail"]
    F --> G["bounded escaped evidence"]
    G --> A
```

## Deliberate limitations

Phase 3 does not provide regex, recursive directory search, file watching, arbitrary
file reads, filesystem mutation, shell execution, networking, ELF inspection, process
observation, worker scheduling, cancellation, or hard per-call deadlines. Processing
is synchronous. The optional legacy path backend has incomplete bind-mount detection.
These limitations are explicit rather than hidden behind security claims.

## Roadmap

1. Phase 0 — foundation, constraints, build, tests, and CI: complete
2. Phase 1 — minimal MCP lifecycle and JSON-RPC over stdio: complete
3. Phase 2 — filesystem policy gate and resource enforcement: complete
4. Phase 3 — streaming log-analysis tools: complete
5. Phase 4 — safe Linux ELF inspection
6. Phase 5 — bounded `/proc` memory observation
7. Phase 6 — coroutine orchestration, cancellation, and backpressure
8. Phase 7 — fuzzing, sanitizer coverage, and security regression suite
9. Phase 8 — deterministic agent investigation demonstration
10. Phase 9 — reproducible benchmarks and reference comparison
11. Phase 10 — release hardening and stable tool interface

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
