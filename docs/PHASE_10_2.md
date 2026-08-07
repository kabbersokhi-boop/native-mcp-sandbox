# Phase 10.2: bounded offline MCP orchestration

Phase 10.2 adds the deterministic external-agent path only.  The native C++
server is unchanged: it has no network, credentials, shell, arbitrary path,
PID, discovery, or control authority.

The Python `McpStdioClient` creates a new allowlisted environment using the
Phase 10.1 policy and launches one trusted executable with a fixed argument
vector and `shell=False`.  Its lifecycle is `start -> initialize ->
notifications/initialized -> tools/list -> serial tools/call -> close`.
Stdin is closed at completion; termination has a bounded grace period followed
by one bounded kill.

Every newline-delimited JSON-RPC message is size checked before parsing,
duplicate JSON keys are rejected, and the response is a closed object with the
exact outstanding integer ID and JSON-RPC version.  The client permits one
outstanding request, so calls cannot overlap.  Exit after transmission is an
ambiguous completion and is never replayed.  Child stdout/stderr, individual
MCP messages, deadlines, and shutdown are bounded.

`tools/list` is a project-owned closed contract.  Tool names are unique, and
the Phase 10.1 closed-schema subset validates every input schema.  Definitions
are frozen, canonicalized, and SHA-256 hashed as the tool-surface identity.

Provider proposals never choose an MCP method.  The orchestrator validates the
full list against that frozen allowlist, derives an action identity from the
surface hash, name, canonical arguments, and local context, then constructs
only `tools/call` requests.  It retains bounded proposal/action state, rejects
provider-ID or content duplicates, and executes valid actions serially in
provider order.  The first rejection, failure, timeout, or cancellation stops
the remaining proposals.

Only a closed, validated `tools/call` result becomes evidence.  Evidence
records the action and locally assigned MCP response ID with
`validated_mcp_evidence` provenance; provider text is never evidence.  The
minimal deterministic transcript records surface identity, local IDs,
authorization/failure control events, order, and outcome.  It excludes child
environment values, credentials, proxies, host paths, raw PIDs, and provider
payload details.

This phase intentionally does not provide live provider transport, credentials,
networking, streaming, reporting, parallel execution, or any Phase 10.3/10.4
claim.
