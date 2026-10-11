# Flagship implementation record

## Scope

Implement the C++ AI infrastructure improvement plan while preserving the four-tool authority
boundary. This record distinguishes source-tree verification from the latest tagged release;
it is not a release assurance claim.

## Baseline: 2026-09-19

- Source: `c195ed03aea5609cd58f8b90764c30a4172f4a0b` (current public main at start).
- Environment: Linux 7.1.3-arch2-2, x86-64; GCC 16.2.1; CMake 4.4.3.
- CMake selected Python 3.12.13. Direct `python3` selected Python 3.14.7.
- Commands: `cmake --preset dev`, `cmake --build --preset dev`, `ctest --preset dev --output-on-failure`.
- Outcome: warnings-as-errors build passed; 21/21 CTest entries passed in 39.39 seconds.
- Added supervised transport tests: two positive cases passed; four stalled-peer cases exceeded
  the five-second supervision deadline; closed stdout exited through SIGPIPE (signal 13).
- All test children were reaped. No hosted model, credentials or host evidence were used.

## Work packages

| Package | Status |
| --- | --- |
| Baseline and boundary wording | Baseline recorded; relative-path and process-privilege wording corrected |
| Native transport liveness | Seven process regressions pass; development and ASan/UBSan suites passed 22/22 after the transport change |
| Installed investigation CLI, three scenarios | Fresh native run passed; 4, 4 and 5 validated responses |
| Generated adversarial evaluation | 25 replayable cases passed for the measured release-build binary |
| Native performance/resource study | Six fixture shapes and three stdio scenarios, with 100 retained samples each |
| Independent MCP client interoperability | Pinned official SDK test passed against the real native process |
| Static trace viewer, recording, public case study | Browser verification passed; silent 1600 × 900 end-to-end film reviewed |
| Packaged release verification and interview material | Extracted native archive and installed wheel passed three scenarios; interview notes prepared |

The latest tagged release remains v0.12.1. The source version is v0.13.0; its evidence must
not be attributed to the older tag. Stretch work and hosted evidence egress are outside
this implementation.

## Integration finding

The five-call hostile scenario exposed a transcript contract mismatch. The producer bounded bytes,
but its parser reused the provider's 32-item collection cap. A legal multistep run could therefore
produce a transcript it could not parse. Control transcripts now have an explicit 128-event budget.
The producer reserves the final event slot for an immutable exhaustion marker. Provider JSON
collections keep their existing limits. Regression tests cover a five-call run and event exhaustion.

## Validation environment

The sandbox denied socket creation in existing provider and Unix-socket tests. It also prevented
LeakSanitizer process inspection. Both complete suites passed when rerun outside that sandbox.
These environment failures were not suppressed by disabling tests or leak detection.
