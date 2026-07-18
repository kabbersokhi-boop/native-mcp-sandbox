# Changelog

All notable changes are recorded here. The project follows semantic versioning after
the first stable release; pre-1.0 versions may change interfaces.

## [Unreleased]

## [0.2.0] - 2026-07-18

### Added

- Bounded newline-delimited JSON-RPC 2.0 transport over stdin/stdout.
- MCP lifecycle support for protocol revision `2025-11-25`.
- `initialize`, `notifications/initialized`, `ping`, and empty `tools/list` handling.
- Structured parse, request, method, parameter, lifecycle, and size errors.
- Protocol unit tests and deterministic process-level stdio coverage.
- System nlohmann/json dependency documentation and attribution.
- ADRs for the JSON dependency and synchronous protocol baseline.

### Changed

- Project version advanced to `0.2.0`.
- Documentation distinguishes the protocol server from future host tools.
- CI installs nlohmann/json 3.11 or newer.

## [0.1.0] - 2026-07-18

### Added

- C++20 CMake project and low-memory build presets.
- Foundation executable with version and self-check commands.
- Validated conservative resource-budget model.
- Unit and command-level CTest coverage.
- GCC, Clang, and sanitizer CI jobs.
- Public architecture, threat model, security, contribution, and roadmap documents.
- ADRs for read-only scope, local stdio transport, and bounded defaults.
