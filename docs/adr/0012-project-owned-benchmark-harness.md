# ADR 0012: project-owned benchmark harness

## Decision

benchmarking uses a small project-owned C++20 harness and a Python stdio orchestrator.

## Context

The harness must build offline, emit machine-readable output, integrate with CMake,
and bound every campaign. An established C++ benchmark library would provide useful
ergonomics, but would add a versioned dependency, vendoring decision, and offline
availability risk for a deliberately small set of bounded cases.

## Consequences

The repository owns simple sampling and summary-statistics code. The C++ target is
enabled only with `NMS_BUILD_BENCHMARKS=ON`. The Python orchestrator measures the
real standard-I/O server, applies output and lifetime limits, and writes canonical
JSON. This is not a general-purpose performance framework.
