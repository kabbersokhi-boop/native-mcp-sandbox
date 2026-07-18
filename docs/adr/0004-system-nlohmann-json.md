# ADR 0004: System-provided nlohmann/json

- Status: Accepted
- Date: 2026-07-18

## Context

Phase 1 must parse untrusted JSON-RPC messages. A custom parser would add unnecessary
correctness and security risk. Downloading dependencies during configuration would
also make restricted and offline builds less predictable.

## Decision

Use nlohmann/json 3.11 or newer from the host system. CMake first uses the package
configuration target and can fall back to installed headers. A compile-time assertion
enforces the minimum version. The repository does not vendor or network-fetch it.

## Consequences

Developers install the distribution package before configuring. Security updates
arrive through the package manager. Compatible patch versions may vary, so protocol
tests remain deterministic and CI records the build environment.
