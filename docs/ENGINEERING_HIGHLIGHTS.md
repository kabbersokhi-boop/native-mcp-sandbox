# Engineering highlights

This guide is a short path from the public design to the implementation and tests. It describes controls and observed test coverage, not security guarantees.

## 1. Threat-boundary design

The native server exposes a deliberately small, read-only evidence surface over stdio. A trusted operator policy maps symbolic aliases to resources; an MCP client never supplies a raw host path or PID. The separate Python agent may ask an optional hosted provider for guidance, but provider output is untrusted and cannot invoke an MCP method directly.

Start with [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`THREAT_MODEL.md`](../THREAT_MODEL.md), and [ADR 0013](adr/0013-external-model-client-boundary.md).

## 2. Filesystem containment

Strict filesystem mode resolves an operator-approved relative path beneath a symbolic root with Linux `openat2`. `RESOLVE_BENEATH`, symlink, magic-link and mount restrictions, plus descriptor ownership, keep resolution tied to the approved directory rather than to a string path re-opened later. The compatibility walk is an explicit opt-in with narrower guarantees.

Implementation: [`src/file_policy.cpp`](../src/file_policy.cpp). Evidence: [`tests/file_policy_tests.cpp`](../tests/file_policy_tests.cpp), [`tests/security_regression_tests.cpp`](../tests/security_regression_tests.cpp), and [ADR 0006](adr/0006-openat2-filesystem-policy.md).

## 3. Process identity

Process access starts with a named policy alias. Strict mode verifies same-UID ownership, retains the process directory, checks start time and pins identity with a pidfd. Those checks address PID reuse without claiming to control a privileged or compromised kernel. Compatibility mode is documented as lacking pidfd pinning.

Implementation: [`src/process_memory.cpp`](../src/process_memory.cpp). Evidence: [`tests/process_memory_tests.cpp`](../tests/process_memory_tests.cpp) and [`SECURITY.md`](../SECURITY.md).

## 4. Resource-bounded protocol parsing

Before JSON objects become protocol or policy state, bounded preflight checks apply byte, token and nesting limits and reject duplicate keys. MCP lifecycle and tool schemas are closed: unknown fields are rejected rather than interpreted permissively. Output is also bounded and complete messages are serialized to stdout.

Implementation: [`src/json_safety.cpp`](../src/json_safety.cpp), [`src/json_rpc.cpp`](../src/json_rpc.cpp), and [`src/server.cpp`](../src/server.cpp). Evidence: [`tests/protocol_tests.cpp`](../tests/protocol_tests.cpp) and the protocol fuzzer described in [`FUZZING.md`](FUZZING.md).

## 5. Concurrency and lifecycle

The native scheduler uses a fixed worker pool and a C++20 coroutine bridge. It bounds unfinished calls, supports cooperative cancellation and steady-clock deadlines, serializes output and makes shutdown ownership explicit. This avoids treating every request as unbounded background work.

Implementation: [`src/orchestration.cpp`](../src/orchestration.cpp). Evidence: [`tests/orchestration_tests.cpp`](../tests/orchestration_tests.cpp), [`tests/orchestration_stress_tests.cpp`](../tests/orchestration_stress_tests.cpp), and [ADR 0010](adr/0010-bounded-coroutine-orchestration.md).

## 6. Agent authority and replay resistance

The external agent captures the native server's exact `tools/list` surface, validates a provider proposal against that surface and the local closed schema, then constructs the MCP `tools/call` itself. Stable action identities and bounded replay state reject duplicate, changed and later-turn proposals. Accepted calls run serially and at most once within one bounded investigation.

Implementation: [`agent/native_mcp_agent/mcp_orchestrator.py`](../agent/native_mcp_agent/mcp_orchestrator.py). Evidence: [`tests/phase_10_2_tests.py`](../tests/phase_10_2_tests.py), [`tests/phase_10_3_tests.py`](../tests/phase_10_3_tests.py), and [`docs/PHASE_10_2.md`](PHASE_10_2.md).

## 7. Provider networking and credentials

Networking is intentionally absent from the C++ server. The optional adapter in the external agent owns endpoint validation, verified HTTPS, bounded non-streaming reads, redirect rejection and credential loading at explicit production execution. A loopback fake-provider path is separate, credential-free and used for offline tests. The implemented egress mode allows only project-authorized synthetic content; later MCP evidence is not sent to a provider.

Implementation: [`agent/native_mcp_agent/openai_compatible.py`](../agent/native_mcp_agent/openai_compatible.py). Evidence: [`tests/phase_10_4_tests.py`](../tests/phase_10_4_tests.py), [`docs/PHASE_10_4.md`](PHASE_10_4.md), and [`SECURITY.md`](../SECURITY.md).

## 8. Assurance

The assurance stack combines focused unit/integration tests, adversarial regressions, sanitizer and ThreadSanitizer runs, deterministic mutation testing, five libFuzzer targets and a byte-stable offline demonstration. Each layer has blind spots; the claim-to-evidence matrix and historical campaign scope are in [`ASSURANCE.md`](ASSURANCE.md).

For a first reproduction, follow the build, test and deterministic demo commands in [`README.md`](../README.md). For release-specific discipline, see [`RELEASING.md`](RELEASING.md).
