# Phase 7 Manifest

## Release identity

- Project: Native MCP Sandbox
- Phase: 7 — Fuzzing, sanitizer depth, and security regression assurance
- Version: 0.8.0
- Prepared: 2026-07-18
- Assurance completed: 2026-07-20
- Baseline commit: `f591b4b6553c29dc37fbeabd45e25def400c4378`
- Baseline tag: `v0.7.0`
- Assured source head: `df576168fd44561254736a60c45188333bd1bc50`
- Target: native Linux with C++20 GCC and Clang
- Protocol revision: `2025-11-25`

## Implemented

- Bounded SAX JSON preflight before DOM construction.
- Duplicate-object-key rejection and explicit nesting/token ceilings.
- Five Clang libFuzzer targets: protocol, runtime policy, ELF, log, and pure process parsers.
- Deterministic shared mutation runner for ordinary and sanitizer builds.
- Curated seed corpora and dictionaries for all fuzz surfaces.
- Pure supplied-byte `/proc` parser interfaces and deterministic parser tests.
- Dedicated security regression suite for hostile JSON and resource boundaries.
- Repeated orchestration stress covering admission, cancellation, deadlines, callbacks, and shutdown.
- Worker-thread factory fault injection and partial-construction cleanup tests.
- Canonical in-flight identity for equal signed/unsigned non-negative JSON-RPC IDs.
- Worker-safe shutdown initiation with deferred non-worker drain and join.
- Separate ASan/UBSan and ThreadSanitizer build modes and native campaign scripts.
- CI jobs for deterministic fuzz smoke, focused race testing, and bounded libFuzzer campaigns.
- Manual Extended Assurance workflow for strict native release evidence.
- ADR 0011 and `docs/FUZZING.md` with triage, minimization, and release-gate guidance.

## Completed assurance

Extended Assurance run `29724493408` and normal CI passed against source head
`df576168fd44561254736a60c45188333bd1bc50` on Ubuntu 24.04.

- Two independent deterministic mutation campaigns completed 100,000 iterations each.
- TSan orchestration unit tests passed 50 repetitions.
- TSan orchestration stress passed 25 repetitions.
- Strict `openat2` and pidfd capability probes passed.
- Real AF_UNIX/FIFO policy tests passed 50 repetitions.
- Configured stdio integration passed 20 repetitions.
- Five 600-second libFuzzer campaigns completed 61,925,751 executions in total.
- No crash, sanitizer finding, timeout, or generated crash artifact was observed.
- Separate evidence artifacts were uploaded for all eight extended jobs.

## Preserved boundaries

- No new MCP tools or host data sources.
- No shell, network, filesystem mutation, process control, or raw memory access.
- Strict `openat2` and pidfd modes remain the defaults.
- Fuzz process inputs are supplied bytes only and do not discover or open host processes.
- Fuzzing and sanitizers are assurance techniques, not proofs of security or correctness.

## Explicitly not implemented

- Docker or container runtime dependency.
- Forced cancellation or hard real-time preemption.
- MCP tasks, durable jobs, dynamic workers, or distributed queues.
- Production incident agent demonstration; that remains Phase 8.
- Benchmark claims; that remains Phase 9.
- Stable 1.0 compatibility guarantees; that remains Phase 10.

## Expected source files

```text
.clang-format
.editorconfig
.github/workflows/ci.yml
.github/workflows/extended-assurance.yml
.gitignore
ARCHITECTURE.md
CHANGELOG.md
CMakeLists.txt
CMakePresets.json
CODE_OF_CONDUCT.md
CONTRIBUTING.md
LICENSE
PHASE_0_MANIFEST.md
PHASE_1_MANIFEST.md
PHASE_2_MANIFEST.md
PHASE_3_MANIFEST.md
PHASE_4_MANIFEST.md
PHASE_5_MANIFEST.md
PHASE_6_MANIFEST.md
README.md
SECURITY.md
THIRD_PARTY_NOTICES.md
THREAT_MODEL.md
docs/FUZZING.md
docs/adr/0001-security-first-read-only-scope.md
docs/adr/0002-local-stdio-transport.md
docs/adr/0003-bounded-low-memory-defaults.md
docs/adr/0004-system-nlohmann-json.md
docs/adr/0005-synchronous-phase-1-protocol.md
docs/adr/0006-openat2-filesystem-policy.md
docs/adr/0007-streaming-literal-log-tools.md
docs/adr/0008-bounded-elf-inspection.md
docs/adr/0009-bounded-proc-memory-observation.md
docs/adr/0010-bounded-coroutine-orchestration.md
docs/adr/0011-native-fuzzing-and-security-regressions.md
fuzz/corpus/elf/elf64-header.bin
fuzz/corpus/elf/magic.bin
fuzz/corpus/log/checkout.log
fuzz/corpus/process/smaps_rollup.txt
fuzz/corpus/process/stat.txt
fuzz/corpus/process/statm.txt
fuzz/corpus/process/status.txt
fuzz/corpus/protocol/cancel.json
fuzz/corpus/protocol/duplicate-key.json
fuzz/corpus/protocol/initialize.json
fuzz/corpus/runtime_config/duplicate-version.json
fuzz/corpus/runtime_config/v1.json
fuzz/corpus/runtime_config/v2.json
fuzz/dictionaries/elf.dict
fuzz/dictionaries/json.dict
fuzz/dictionaries/log.dict
fuzz/dictionaries/process.dict
fuzz/fuzz_elf.cpp
fuzz/fuzz_log.cpp
fuzz/fuzz_process.cpp
fuzz/fuzz_protocol.cpp
fuzz/fuzz_runtime_config.cpp
fuzz/fuzz_smoke.cpp
fuzz/fuzz_support.cpp
fuzz/fuzz_support.hpp
include/native_mcp/elf_analysis.hpp
include/native_mcp/file_policy.hpp
include/native_mcp/foundation.hpp
include/native_mcp/json_rpc.hpp
include/native_mcp/json_safety.hpp
include/native_mcp/log_analysis.hpp
include/native_mcp/operation.hpp
include/native_mcp/orchestration.hpp
include/native_mcp/process_memory.hpp
include/native_mcp/process_parsing.hpp
include/native_mcp/runtime_config.hpp
include/native_mcp/server.hpp
include/native_mcp/tool_service.hpp
scripts/run_fuzz_campaign.sh
scripts/run_security_stress.sh
src/elf_analysis.cpp
src/file_policy.cpp
src/foundation.cpp
src/json_rpc.cpp
src/json_safety.cpp
src/log_analysis.cpp
src/main.cpp
src/orchestration.cpp
src/process_memory.cpp
src/runtime_config.cpp
src/server.cpp
src/tool_service.cpp
tests/elf_analysis_tests.cpp
tests/file_policy_tests.cpp
tests/foundation_tests.cpp
tests/json_safety_tests.cpp
tests/log_analysis_tests.cpp
tests/orchestration_stress_tests.cpp
tests/orchestration_tests.cpp
tests/process_memory_tests.cpp
tests/process_parsing_tests.cpp
tests/protocol_tests.cpp
tests/security_regression_tests.cpp
tests/stdio_integration_tests.cpp
PHASE_7_MANIFEST.md
```

Build directories, generated corpora, crash artifacts, binaries, objects, Git metadata,
credentials, local paths, archives, private prompts, and audit notes are excluded.
