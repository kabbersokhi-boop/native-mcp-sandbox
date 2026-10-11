# Independent MCP client compatibility

The native server targets MCP revision `2025-11-25`. The independent check uses the official
TypeScript SDK, `@modelcontextprotocol/sdk` version `1.30.0`, pinned with its transitive lockfile.
This dependency is test-only. The native server and Python package do not acquire a Node runtime.

```bash
cd tests/interop
npm ci --ignore-scripts --no-audit --no-fund
NMS_SERVER=../../build/dev/native-mcp-sandbox npm test
```

The check starts the real server through `StdioClientTransport`. It verifies initialization,
notifications, ping, the exact four-tool surface, structured responses from all four tools,
concurrent response correlation, strict pidfd observation, traversal rejection and unknown-process
errors. A separate test-only raw transport exercises malformed envelopes and direct native denials.

This is a tested interoperability subset, not an assertion of full upstream conformance.
The project does not implement Streamable HTTP, arbitrary tasks, resource subscriptions or
every optional MCP feature. Those features are outside its stated stdio evidence scope.

Reviewed upstream on 2026-09-19: the conformance project's documented server runner takes
an HTTP `--url`, not a stdio executable. Initialization, tool discovery, tool success/error
semantics and correlation apply conceptually and are exercised by our independent SDK test;
HTTP transport/auth suites do not apply. We did not add an HTTP shim or count unexecuted
upstream cases as passing. Newer protocol work changes lifecycle assumptions; this candidate
continues to target `2025-11-25` and does not claim the newer revision.

For manual inspection, run the MCP Inspector with the same pinned SDK-era protocol and a synthetic
policy. Use the server command `./build/dev/native-mcp-sandbox --policy-config /absolute/policy.json`.
The Inspector is a development tool, not an additional server transport. Its UI is not a release gate.

Client configuration shape:

```json
{
  "command": "/absolute/path/native-mcp-sandbox",
  "args": ["--policy-config", "/absolute/path/synthetic-policy.json"],
  "env": {"LANG": "C"}
}
```

This configuration is exercised by the SDK test. Other host-specific configuration formats are
not claimed as verified. See the [official SDK](https://github.com/modelcontextprotocol/typescript-sdk)
and [upstream conformance project](https://github.com/modelcontextprotocol/conformance).
