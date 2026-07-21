# Phase 8 plan — deterministic agent investigation demonstration

Phase 8 demonstrates how an agent can conduct a small, reproducible investigation using the existing bounded MCP tools without adding host authority, networking, shell execution, unrestricted file access, or an LLM dependency.

## Release target

- Planned version: `0.9.0`
- Base release: `v0.8.0`
- Base commit: `486a3a7c9fdf90f54e74e87c7ae68a245a9cc53c`

## Security boundary

Phase 8 must not add a new MCP tool or broaden any existing input schema. The demonstration may call only:

1. `logs.search`
2. `logs.tail`
3. `elf.inspect`
4. `proc.memory`

All filesystem paths and process targets remain operator-configured aliases. The demonstration must not accept arbitrary absolute paths, raw PIDs, shell fragments, URLs, or executable commands from its investigation plan.

## Demonstration scenario

A committed synthetic incident fixture represents a service restart followed by an authentication failure and a bounded recovery. A deterministic client launches the real `native-mcp-sandbox` executable with a temporary policy rooted at the fixture directory, completes the MCP lifecycle, discovers the four tools, and executes a fixed investigation plan.

The plan will:

1. search the synthetic application log for the incident correlation identifier;
2. search for bounded error indicators;
3. tail the final recovery lines;
4. inspect a generated minimal non-executable ELF fixture;
5. observe the configured server process only;
6. convert structured tool results into a canonical evidence record;
7. emit deterministic JSON and Markdown reports.

Raw process counters, PIDs, addresses, timestamps generated at runtime, and other machine-dependent values must not appear in the canonical report. The report may state only stable predicates derived from them, such as whether process observation succeeded, whether pidfd pinning was active, and whether required memory counters were present.

## Determinism requirements

- The tool-call sequence, request IDs, arguments, and evidence ordering are fixed.
- JSON output uses sorted keys and a final newline.
- Markdown section and finding order are fixed.
- The same executable and fixtures run twice in one test must produce byte-identical canonical reports.
- A committed golden JSON report defines the expected investigation conclusions.
- Tests must fail on a missing response, extra response, tool error, schema mismatch, changed finding, changed ordering, or nondeterministic output.

## Planned repository changes

- `scripts/run_agent_investigation_demo.py` — standard-library MCP client and canonical report generator.
- `demo/investigation/application.log` — synthetic incident fixture.
- `demo/investigation/expected-report.json` — golden canonical result.
- `tests/agent_investigation_demo_test.py` — two-run reproducibility and golden-output test.
- CMake/CTest integration for the demonstration test.
- README, architecture, changelog, and Phase 8 manifest updates.

## Verification gates

Phase 8 is not complete until all of the following pass on the final branch head:

- GCC Debug build, CTest, and self-check;
- Clang Release build, CTest, and self-check;
- ASan/UBSan with leak detection;
- focused TSan orchestration tests;
- existing libFuzzer smoke jobs;
- deterministic investigation test in strict `openat2` and pidfd mode on GitHub Actions;
- two-run byte-for-byte JSON and Markdown equality;
- golden report equality;
- public audit confirming no new host authority and no Phase 9 work.

## Explicit non-claims

The demonstration is not autonomous incident response, a production agent framework, a correctness proof, or evidence that all defects are absent. It is a reproducible example of bounded evidence collection and deterministic conclusion formatting over synthetic fixtures.
