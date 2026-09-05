# Demonstrations

Native MCP Sandbox includes two different demonstrations. They serve different purposes and have different trust boundaries.

## 1. Deterministic offline investigation

This is the primary reproducible demonstration.

It uses:

- the real C++ MCP server;
- a generated runtime policy;
- a committed synthetic incident log;
- a non-executable ELF fixture;
- the four existing read-only tools;
- canonical JSON and Markdown output.

It does not require a hosted model, a credential or internet access.

### Build

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure
```

### Run

```bash
mkdir -p build/agent-investigation-output

python3 scripts/run_agent_investigation_demo.py \
  --server ./build/dev/native-mcp-sandbox \
  --fixture ./demo/investigation/application.log \
  --output-dir ./build/agent-investigation-output
```

### Output

```text
build/agent-investigation-output/report.json
build/agent-investigation-output/report.md
```

The committed reference outputs are in [`demo/investigation/`](../demo/investigation/).

### What the demonstration proves

For the tested build, the client:

1. starts the real server over stdio;
2. completes the MCP lifecycle;
3. verifies the exact advertised tool surface;
4. performs bounded log, ELF and process observations;
5. correlates responses by JSON-RPC ID;
6. converts runtime observations into stable predicates;
7. emits canonical reports;
8. reproduces byte-identical output across repeated runs.

### What it does not prove

The demonstration is synthetic. It is not autonomous incident response, a production monitoring service, or proof that every security defect is absent.

## 2. Optional OpenAI-compatible synthetic smoke

The optional adapter includes a manual, non-gating smoke command for an operator-selected
OpenAI-compatible endpoint. It can use NVIDIA NIM or another compatible service, but the project
does not hard-code a provider, endpoint, or model.

The smoke is disabled by default and is never part of normal CI.

```bash
python3 scripts/openai_adapter_smoke.py \
  --enable-synthetic-live \
  --endpoint https://provider.example/v1/chat/completions \
  --model operator-selected-model \
  --credential-env NATIVE_MCP_PROVIDER_TOKEN
```

### Safety properties

- The prompt is project-authorized synthetic material.
- The credential is loaded only at explicit production HTTPS execution.
- The credential is not placed in argv, transcripts or native-server state.
- The response body is bounded and parsed through a closed schema.
- Provider text is not printed as evidence.
- The result is observational only and cannot satisfy a CI or merge gate.
- The loopback fake-provider path is structurally credential-free.

### No credential example

Do not place a real token in documentation, a command line or a committed file. Set the configured environment variable in the operator environment immediately before an explicitly authorized smoke run.

## Related documents

- [`README.md`](../README.md) — project overview and quick start
- [`docs/OPENAI_COMPATIBLE_ADAPTER.md`](OPENAI_COMPATIBLE_ADAPTER.md) — adapter design and boundaries
- [`docs/ASSURANCE.md`](ASSURANCE.md) — verification evidence and reproducible test commands
- [`SECURITY.md`](../SECURITY.md) — security policy and vulnerability reporting
