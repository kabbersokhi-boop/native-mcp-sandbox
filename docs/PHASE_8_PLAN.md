# Phase 8 plan: deterministic agent investigation demonstration

Phase 8 will show one small and reproducible investigation.
The demonstration will use the existing MCP tools.
It will not add host authority.
It will not require an LLM.

## Release target

- Candidate version: `0.9.0`
- Base release: `v0.8.0`
- Base commit: `486a3a7c9fdf90f54e74e87c7ae68a245a9cc53c`

## Security boundary

Phase 8 must not add an MCP tool.
It must not change an existing tool input schema.

The demonstration can call only these tools:

1. `logs.search`
2. `logs.tail`
3. `elf.inspect`
4. `proc.memory`

The runtime policy controls each filesystem root and process target.
The demonstration plan must not accept these inputs:

- an absolute path
- a raw PID
- a shell fragment
- a URL
- an executable command

## Scenario

A committed synthetic fixture represents this sequence:

1. A service restarts.
2. An authentication failure occurs.
3. The service completes a bounded recovery.

A deterministic client will start the real `native-mcp-sandbox` executable.
It will use a temporary policy for the fixture directory.
It will complete the MCP lifecycle.
It will verify the four available tools.
Then it will run one fixed investigation plan.

The plan will do these actions:

1. Search the application log for the incident correlation ID.
2. Search the log for bounded error indicators.
3. Read the final recovery lines.
4. Inspect a generated minimal non-executable ELF file.
5. Observe the configured server process only.
6. Convert the structured tool results to a canonical evidence record.
7. Write deterministic JSON and Markdown reports.

The fixed tool sequence uses these request IDs:

1. Search `INC-042` with case-sensitive matching.
2. Search `ERROR` with case-sensitive matching.
3. Read the final three log lines.
4. Inspect the generated ELF fixture.
5. Observe the configured `server` process alias.

## Canonical output

The canonical report must not contain a machine-dependent value.
It must not contain these values:

- raw process counters
- PIDs
- memory addresses
- runtime-generated timestamps
- host-specific paths

The report can contain stable predicates.
Examples include these predicates:

- process observation succeeded
- pidfd pinning was active
- required memory counters were present
- the expected log evidence was present
- the ELF fixture had the expected identity

## Determinism requirements

The demonstration must meet these requirements:

- The tool order is fixed.
- The request IDs are fixed.
- The tool arguments are fixed.
- The evidence order is fixed.
- JSON keys are sorted.
- Each output file has one final newline.
- Markdown sections have a fixed order.
- Two runs produce byte-identical JSON.
- Two runs produce byte-identical Markdown.
- A committed golden JSON file defines the expected conclusions.

A test must fail for one of these conditions:

- missing response
- extra response
- tool error
- schema mismatch
- changed finding
- changed order
- nondeterministic output
- non-empty standard error in strict mode
- a non-zero server exit
- an output timeout or byte-limit violation

## Planned files

- `scripts/run_agent_investigation_demo.py`
- `demo/investigation/application.log`
- `demo/investigation/expected-report.json`
- `demo/investigation/expected-report.md`
- `tests/agent_investigation_demo_test.py`
- CMake and CTest integration
- Phase 8 documentation and manifest updates

## Verification gates

Phase 8 is complete only when the final branch head passes these gates:

- GCC Debug build, CTest, and self-check
- Clang Release build, CTest, and self-check
- ASan and UBSan with leak detection
- focused ThreadSanitizer tests
- existing libFuzzer smoke tests
- strict `openat2` and pidfd demonstration test
- two-run JSON equality
- two-run Markdown equality
- golden report equality
- public audit of the unchanged host boundary

Final assurance remains pending until the required CI jobs pass on the final
branch head.

## Non-claims

The demonstration is not autonomous incident response.
It is not a production agent framework.
It is not proof of correctness.
It is not proof that all defects are absent.
It is one reproducible example of bounded evidence collection over synthetic data.
