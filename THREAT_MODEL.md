# Threat Model

## Status and scope

This document describes the intended security model and the controls established in
Phase 0. The current executable is a foundation self-check and does not yet accept
MCP requests or inspect files.

The project assumes an AI client may produce incorrect, adversarial, oversized, or
unexpected tool arguments. It also assumes inspected files may be malicious.

## Assets to protect

- files outside explicitly configured analysis roots;
- integrity of all host files, including files inside permitted roots;
- availability and memory of the host machine;
- correctness of MCP protocol output;
- privacy of unrelated process information; and
- confidentiality of data not required for a tool response.

## Intended attacker capabilities

An attacker may influence agent prompts, MCP arguments, file names, file contents,
process IDs, request order, request volume, and cancellation timing. The attacker may
attempt path traversal, symbolic-link escapes, parser abuse, resource exhaustion,
response amplification, or concurrency races.

## Security goals

The finished server should:

1. expose only named, schema-validated tools;
2. deny filesystem access outside configured roots;
3. remain read-only and never execute inspected binaries;
4. bound memory, output, pending work, worker count, and operation duration;
5. fail closed when authorization or validation is uncertain;
6. preserve valid protocol framing under concurrency; and
7. return only the evidence necessary for the requested analysis.

## Phase 0 controls

- Conservative resource defaults are represented in code.
- Hard upper bounds reject nonsensical budget configurations.
- Build presets support AddressSanitizer and UndefinedBehaviorSanitizer.
- The test harness checks resource-budget validation.
- No file, process, network, shell, or protocol capabilities are present yet.

## Planned controls

- strict JSON-RPC envelope and MCP schema validation;
- canonical-path and descriptor-based filesystem checks;
- symbolic-link and time-of-check/time-of-use defenses;
- allowlisted analysis roots and permitted process identities;
- bounded streaming parsers and result truncation metadata;
- deadlines, cooperative cancellation, bounded queues, and backpressure;
- fuzz targets for protocol, log, and ELF parsing;
- privilege reduction and optional Linux OS-level isolation; and
- security regression tests for every disclosed vulnerability.

## Explicit non-goals

- arbitrary shell access;
- remote network service operation;
- executing or dynamically loading inspected binaries;
- modifying, deleting, or repairing local files;
- protecting against a compromised kernel or privileged host administrator; and
- claiming that application validation alone is equivalent to a hardened OS sandbox.

## Residual risks

Native parsers can contain memory-safety defects despite careful C++ practices.
Filesystem authorization is vulnerable to subtle races if implemented only with
string paths. Resource bounds reduce denial-of-service risk but cannot eliminate all
CPU, disk, or kernel-level contention. Optional OS isolation will depend on the
host's Linux configuration.

Every release must update this document when a capability or trust assumption
changes.
