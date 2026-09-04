# ADR 0004: System nlohmann/json dependency

- Status: Accepted
- Date: 2026-07-18

## Context

initial protocol must parse untrusted JSON-RPC messages.
A custom JSON parser would add unnecessary correctness and security risk.
A configuration-time download would make restricted and offline builds less predictable.

## Decision

Use nlohmann/json 3.11 or newer from the host system.
CMake first uses the package configuration target.
If that target is not available, CMake uses installed headers.
A compile-time check enforces the minimum version.
Do not vendor or download this dependency from the build.

## Consequences

A developer must install the distribution package before configuration.
The package manager supplies security updates.
Patch versions can differ between systems.
Therefore, protocol tests must stay deterministic and CI must record its environment.
