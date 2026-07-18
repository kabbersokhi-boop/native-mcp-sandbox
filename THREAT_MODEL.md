# Threat Model

## Status and scope

The Phase 1 executable accepts MCP/JSON-RPC messages over local stdio, but exposes no
host-access or analysis tool. Tool discovery returns an empty list.

The project assumes an AI client may produce incorrect, adversarial, oversized, or
unexpected input. Future inspected files must also be treated as malicious.

## Assets to protect

- availability and memory of the host process;
- correctness and framing of MCP output;
- confidentiality of request contents not needed in diagnostics;
- files outside future configured roots;
- integrity of all host files; and
- privacy of unrelated process information.

## Attacker capabilities

An attacker may influence message bytes, JSON nesting and types, IDs, methods,
parameters, request order, line length, notification volume, and shutdown. Later the
attacker may also influence paths, file contents, process IDs, and cancellation timing.

## Phase 1 security goals

1. Accept only one bounded JSON message per line.
2. Reject malformed or invalid requests with bounded errors.
3. Never write diagnostics or arbitrary text to stdout in server mode.
4. Avoid echoing untrusted request contents to stderr.
5. Preserve lifecycle state after failed validation or oversized responses.
6. Avoid responding to valid notifications.
7. Expose no analysis or host-access capability.
8. Terminate cleanly on EOF.

## Implemented controls

- 1 MiB default request and response limits.
- Incremental line reading that stops buffering and drains oversized messages.
- JSON-RPC envelope, method, parameter, and request-ID validation.
- Rejection of fractional IDs and top-level arrays.
- Explicit MCP initialization and ready states.
- Empty `tools/list` and no `tools/call` implementation.
- Generic stderr diagnostics without request payloads.
- One synchronous logical stdout writer.
- Strict warning builds, process integration tests, ASan, and UBSan support.
- No file, process, shell, or network operation in reachable code.

## Explicit non-goals

- arbitrary shell access;
- remote network service operation;
- executing or loading inspected binaries;
- modifying, deleting, or repairing files;
- protecting against a compromised kernel or privileged administrator; and
- claiming application validation is equivalent to an OS sandbox.

## Residual risks

nlohmann/json builds an in-memory tree for each accepted message, so a request near the
wire-size limit can consume more memory than its original bytes. The limit reduces but
does not eliminate parser CPU or memory denial-of-service risk. Deep nesting may be
expensive. Phase 1 has no per-message execution deadline because it is synchronous.

Native C++ code can contain memory-safety defects despite sanitizer testing.
Distribution-provided dependencies require security updates. The process has the same
permissions as the launching user; this has limited impact while no host-access code
exists, but later phases require policy enforcement and optional OS isolation.

Every release must update this document when capabilities or assumptions change.
