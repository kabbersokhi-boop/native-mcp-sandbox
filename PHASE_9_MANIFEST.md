# Phase 9 manifest

Framework: project-owned C++20 harness (`1.0.0`) plus bounded Python stdio driver.
ADR 0012 records the offline-build and dependency trade-off.

Implemented cases: JSON SAX valid/rejected, JSON DOM closed-schema subset,
runtime-policy parsing, supplied proc-text parsing, strict-fixture log search/tail
and ELF inspection, and end-to-end lifecycle/tools-list plus all four tool calls.
The configured end-to-end set is concurrent below the production admission limit.

Fixtures are committed, deterministic, and contain no host data: a 56-byte log with
three matches, a 64-byte minimal ELF, supplied proc text, and the Phase 8 log.
Fixture set version is `1.0.0`.

Limits: 256 KiB benchmark stdout/report, 64 KiB stderr, ten-second subprocess life,
15 retained samples, and no partial report after failure. Every valid sample is
retained; the report explicitly records zero exclusions.

Semantic evidence: each measured operation validates its fixed result before its
sample is recorded. The JSON DOM/SAX pair uses one identical valid request. Streaming
versus whole-buffer references are documented but not implemented in this initial
bounded harness because a whole-buffer implementation would duplicate production
logic and requires independent review of all truncation semantics.

Omitted candidates: scheduler admission/completion/cancellation/saturation and the
Phase 8 investigation invocation are not yet timed as standalone cases; they remain
covered by existing orchestration and deterministic-investigation tests. On hosts
without strict `openat2`, log/ELF and configured end-to-end cases are unavailable;
the harness does not fall back. No raw PID, process discovery, shell execution,
networking, filesystem capability, or production security control was added.

Non-claims: no universal performance, production-readiness, correctness, security,
or cross-machine ranking claim is made. No reduced-control path is deployable.
