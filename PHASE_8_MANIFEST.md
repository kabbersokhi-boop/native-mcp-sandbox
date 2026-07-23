# Phase 8 manifest

## Release identity

- Candidate version: `0.9.0`.
- Phase: 8 deterministic agent investigation demonstration.
- Base tag: `v0.8.0`.
- Base commit: `486a3a7c9fdf90f54e74e87c7ae68a245a9cc53c`.
- Implementation branch: `phase/8-deterministic-agent-demo`.

Phase 8 assurance passed for implementation head
`3db672ee65ebaca048d7e1f9490c6ad43aeb4ec4`.
The assurance record covers the exact source head and CI run below.

## Implemented files

- `scripts/run_agent_investigation_demo.py`
- `tests/agent_investigation_demo_test.py`
- `demo/investigation/application.log`
- `demo/investigation/expected-report.json`
- `demo/investigation/expected-report.md`
- `CMakeLists.txt`
- `README.md`
- `ARCHITECTURE.md`
- `CHANGELOG.md`
- `SECURITY.md`
- `THREAT_MODEL.md`
- `docs/PHASE_8_PLAN.md`
- `src/foundation.cpp`
- `tests/foundation_tests.cpp`
- `tests/protocol_tests.cpp`
- `tests/stdio_integration_tests.cpp`

## Security boundary

The demonstration uses the real `native-mcp-sandbox` executable.
It uses the MCP standard-I/O interface.
It uses only `logs.search`, `logs.tail`, `elf.inspect`, and `proc.memory`.
It does not add a tool or change a tool schema.
It does not use shell execution, network access, filesystem mutation, process
control, raw PIDs, raw process memory, an LLM, a third-party Python package, or
a container.
It runs without the legacy descriptor-walk and process-pinning flags.

## Deterministic output rules

- Use fixed request IDs and fixed arguments.
- Correlate responses by JSON-RPC ID.
- Use a fixed evidence order.
- Sort JSON keys and use two-space indentation.
- End JSON and Markdown with one newline.
- Convert runtime process values to stable predicates.
- Exclude PIDs, UIDs, counters, addresses, temporary paths, and timestamps.

## Verification requirements

- Complete the MCP initialization lifecycle.
- Verify the exact four-tool list.
- Validate every response and tool result.
- Require strict `openat2` and pidfd operation.
- Run the real demonstration twice in separate output directories.
- Require byte-identical JSON and Markdown output.
- Require equality with both committed golden files.
- Run `agent.investigation_demo` in GCC, Clang, and sanitizer CTest suites.
- Pass all five required GitHub Actions jobs.

## Assurance record

- Source head: `3db672ee65ebaca048d7e1f9490c6ad43aeb4ec4`.
- CI run: `30007718678`.
- GCC Debug: job `89207709631`, passed.
- Clang Release: job `89207709564`, passed.
- ASan and UBSan: job `89207709522`, passed.
- ThreadSanitizer orchestration: job `89207709779`, passed.
- libFuzzer corpus and mutation smoke: job `89207709620`, passed.

## Explicit non-claims

The demonstration is not autonomous incident response.
It is not a production agent framework.
It is not proof of complete correctness or security.
It is not a benchmark.
It does not claim that all defects are absent.

## Expected source files

The expected source files are the implemented files listed above and the
unchanged server sources that provide the four existing MCP tools.
The demonstration must continue to use the existing server boundary.

## Excluded generated material

Do not commit build directories, temporary demonstration roots, runtime policy
files, generated ELF files, runtime transcripts, or test output.
The two golden reports and the committed log fixture are source evidence.
