# Native MCP Agent

`native-mcp-agent` is the optional, provider-neutral client for the Native MCP Sandbox server.
It is a separate Python process and a separate trust boundary from the native C++ server.

The agent:

- captures the exact MCP tool surface before it asks a provider for a proposal;
- validates tool names and arguments against closed local schemas;
- derives stable action identities and rejects replay;
- executes MCP calls serially through one bounded child-process lifecycle;
- records bounded, redacted control transcripts and source provenance;
- keeps provider credentials and network access outside the native server.

## Install from this repository

```bash
python -m pip install ./agent
```

## Run the native investigation demo

Install or build the native server, then run:

```bash
native-mcp-agent demo --server /path/to/native-mcp-sandbox --output demo-output
```

The default runs three synthetic scenarios: recovery, incomplete evidence and hostile proposals.
Each uses the real C++ tools through the shipped Python orchestrator. No provider key or network
connection is required. Use `--scenario recovered`, `inconclusive` or `hostile` for one scenario.

Each scenario writes `report.json`, `report.md`, `transcript.json` and `run.json`.
The report separates observed facts, inferences, unresolved questions and boundary decisions.
The hostile case distinguishes a native traversal rejection from a Python unknown-tool rejection.
Proposals are scripted. This tests enforcement, not live-model susceptibility to prompt injection.

`run.json` contains local paths, timing and redacted process observations. Publish the canonical
report, not local run metadata. The demo requires strict `openat2` and pidfd support and never
enables compatibility flags automatically.

The package has no runtime dependency on a provider SDK. The OpenAI-compatible adapter uses the
Python standard library and is opt-in. Deterministic tests use a loopback fake provider and require
no credential.

## Trust boundary

A model can propose a call. It cannot execute a tool, expand the captured tool surface, create
valid evidence, or grant itself authority. Local code validates every transition.

This package is a preview interface. Validate it against the exact native-server commit that you
intend to use. See [bounded orchestration](../docs/MCP_ORCHESTRATION.md),
[provider contracts](../docs/PROVIDER_CONTRACTS.md), and the
[OpenAI-compatible adapter](../docs/OPENAI_COMPATIBLE_ADAPTER.md).
