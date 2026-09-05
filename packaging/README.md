# Native MCP Sandbox binary package

This package contains the Linux x86-64 build of `native-mcp-sandbox`.

Run these checks after extraction:

```bash
./bin/native-mcp-sandbox --version
./bin/native-mcp-sandbox --self-check
```

The server reads newline-delimited JSON-RPC from standard input and writes responses to standard
output. Supply an explicit runtime policy with `--policy-config`. Without a trusted policy, the
server advertises no host-evidence tools.

The GitHub Release contains the source, full documentation, SBOMs, SHA-256 checksums, and build
provenance. This package also contains the Apache-2.0 license and third-party notices.
