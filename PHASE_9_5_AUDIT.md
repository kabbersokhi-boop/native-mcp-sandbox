# Phase 9.5 independent release audit

Audit target: draft PR #12, branch
`agent/phase-9-5-independent-audit`, based on `main` at release commit
`ee989929c490f72513c9cdf9b6180449059c4b65` and tag `v0.10.0`.

This audit corrects post-release consistency defects and records a bounded
native validation campaign. The immutable `v0.10.0` tag remains unchanged. The
current main-line correction prepares patch release `v0.10.1`; it must not be
tagged until PR #12 is merged and the exact merge commit passes push-triggered
`main` CI. This audit does not add an agent, a model provider, networking,
credentials, new MCP tools, or new host authority. Phase 10 has not started.

## Repository state

Verified before correction:

- GitHub connector account: `kabbersokhi-boop`.
- PR #12: open, draft, mergeable, based on `main`; no review threads.
- `origin/main`: `ee989929c490f72513c9cdf9b6180449059c4b65`.
- `v0.10.0`: `ee989929c490f72513c9cdf9b6180449059c4b65`.
- The original worktree contained unrelated untracked `scripts/__pycache__/`;
  it was not staged or removed.

This document intentionally does not embed a mutable final PR-head SHA or
workflow-run identifier. Exact revisions below identify the commits on which
specific local campaigns ran; the final PR-head checks are recorded in the
PR checks and body.

The shell `gh auth status` reported the configured token as invalid, while the
connected GitHub account was usable for PR metadata. Direct shell fetch needed
network-enabled execution because sandbox DNS was unavailable.

## Confirmed findings and corrections

### Release-version drift — high priority — VERIFIED/CORRECTED

`CMakeLists.txt`, `native_mcp::project_version()`, and foundation/protocol
integration tests reported `0.9.0` while the immutable released tag was
`v0.10.0`. The runtime version was therefore inconsistent with the package
identity. This is a defect in the existing tag; this PR does not rewrite that
tag.

`project(... VERSION 0.10.1)` is now the only project version literal used to
produce the planned correction binary. CMake configures
`cmake/native_mcp_version.hpp.in` into a private generated include directory
used by the foundation target. The `foundation.version_output` CTest invokes
the executable directly and requires the exact output
`native-mcp-sandbox 0.10.1`. The C++ foundation test and MCP integration
expectations also require `0.10.1`.

### Release documentation drift — medium priority — VERIFIED/CORRECTED

README release text and roadmap were stale, and its GitHub Release badge was
misleading because `v0.10.0` is an annotated tag without a GitHub Release
object. The badge now targets tags. README, `PHASE_9_MANIFEST.md`,
`ARCHITECTURE.md`, and `SECURITY.md` identify `v0.10.0` as the immutable
original Phase 9 tag and `v0.10.1` as the untagged current correction; Phases
0–9 are marked complete, Phase 10 is marked not started, and Phase 9 bounded
reproducibility benchmarks are described. Historical Phase 8 references in
`PHASE_8_MANIFEST.md` and `CHANGELOG.md` remain historical.

The demonstration's current executable expectation is now `0.10.1`, including
its committed golden report. The original `v0.10.0` release sequence and
historical Phase 8 candidate record are not rewritten.

### Benchmark metadata — medium priority — VERIFIED/CORRECTED

The old CI metadata recorded the package name rather than its installed
version, and compile/link evidence was normally unavailable. The benchmark
driver now:

- uses `dpkg-query -W -f='${Package}=${Version}\n' nlohmann-json3-dev` when no
  CI-provided value exists;
- reads `CMakeCache.txt` for build type, generator, and relevant CMake options;
- reads `compile_commands.json` for actual compile flags;
- reads bounded Ninja link commands for actual link flags/commands;
- records compiler identity and full compiler version, executable hashes,
  repository commit, dirty state, CMake version, and command-line arguments;
- probes the CPU governor, Intel pstate/CPU boost state, and virtualization
  read-only, recording an unavailable reason when absent.

CI benchmark configurations now enable
`-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` and export the installed dependency
version from `dpkg-query` into the benchmark environment. No guessed flags or
host configuration changes were introduced. On this EndeavourOS host, `dpkg-query` and
virtualization identification were unavailable and the generated report
recorded both honestly. The governor was `powersave` and turbo was observed as
`enabled`; neither was changed.

### Offline schema validator — medium priority — VERIFIED/CORRECTED

The validator previously accepted non-finite numbers because comparisons with
NaN do not fail, did not validate the schema tree before walking reachable
values, and did not enforce schema structure types robustly. It now strictly
implements every keyword used by the repository schema: `type`, `required`,
`properties`, `items`, `minItems`, `maxItems`, `pattern`, `const`,
`additionalProperties`, and `minimum`. Booleans are excluded from integer and
number types, numbers must be finite, and unsupported or malformed schema
constructs fail explicitly. Metadata availability, sample accounting, and
comparison-group references remain checked as repository invariants.

Named negative coverage now includes booleans-as-numbers, NaN/infinity, missing
required fields, unexpected fields, malformed availability records, empty and
excessive samples, wrong units, invalid comparison groups, incorrect complete
flags, sample accounting mismatch, and an unsupported schema keyword.

### Deterministic demo output-directory harness — low priority — VERIFIED/CORRECTED

The prescribed two-run demonstration command starts from `rm -rf` output paths,
but the client rejected non-existent output directories. The client now creates
the requested directory and has a regression test for that path. It still
removes stale reports before running and atomically writes only completed
reports.

### CI supply-chain posture — FOLLOW-UP/UNRESOLVED

`.github/workflows/ci.yml` retains read-only `contents: read` permissions and
does not add write permissions. `actions/checkout@v4` remains a moving major
tag. Immutable pinning was not guessed or applied because this bounded PR does
not yet provide a reviewed SHA-update process such as Dependabot or a periodic
maintainer procedure. A future reviewed supply-chain change should resolve the
official upstream tag-to-commit mapping and document its update process.

## Exact validation evidence

### Verified build and test results

- Environment capture command beginning `uname -a` through
  `git status --porcelain`: completed on Linux EndeavourOS, CMake 4.4.0, Ninja
  1.13.2, GCC/G++ 16.1.1, Clang/Clang++ 22.1.8, Python 3.14.6.
- `rm -rf build/dev; cmake --preset dev; cmake --build --preset dev`:
  VERIFIED with GCC Debug.
- `ctest --preset dev --output-on-failure`: first sandboxed run was
  ENVIRONMENTAL (`policy.unit` Unix socket: `Operation not permitted`, 15/16);
  the same command outside the restrictive sandbox was VERIFIED, 16/16.
- `./build/dev/native-mcp-sandbox --version`: VERIFIED, exact
  `native-mcp-sandbox 0.10.1`.
- `./build/dev/native-mcp-sandbox --self-check`: VERIFIED.
- `python3 tests/benchmark_metadata_tests.py` and
  `python3 tests/benchmark_failure_tests.py`: VERIFIED after the patch-release
  correction.
- `rm -rf build/release; cmake --preset release; cmake --build --preset
  release`: VERIFIED with GCC Release.
- `ctest --preset release --output-on-failure`: VERIFIED, 16/16 outside the
  restrictive sandbox.
- `./build/release/native-mcp-sandbox --version`: VERIFIED, exact
  `native-mcp-sandbox 0.10.1`.
- `./build/release/native-mcp-sandbox --self-check`: VERIFIED.
- `python3 scripts/run_agent_investigation_demo.py --server
  ./build/release/native-mcp-sandbox --fixture
  ./demo/investigation/application.log --output-dir
  ./build/audit-version-demo`: VERIFIED; generated report and committed golden
  report identify version `0.10.1`.
- `rm -rf build/sanitizers; cmake --preset sanitizers; cmake --build --preset
  sanitizers`: VERIFIED.
- ASan/UBSan CTest with
  `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1:strict_string_checks=1` and
  `UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`: VERIFIED, 16/16.
- `CXX=g++ cmake --preset thread-sanitizer` plus build and
  `TSAN_OPTIONS=halt_on_error=1 ctest ... -R '^orchestration\\.(unit|stress)$'`:
  VERIFIED, 2/2; no race or unsupported-runtime diagnostic.

### Benchmark campaign

- GCC benchmark-aware configure/build with Release, warnings-as-errors,
  benchmarks, Ninja, and compile commands: VERIFIED.
- GCC benchmark-aware CTest: VERIFIED, 18/18.
- The current GCC benchmark report recorded turbo `enabled`; the host exposed
  Intel `no_turbo=0` and did not expose generic `cpufreq/boost`, so the result
  follows the Intel mapping.
- `NMS_REQUIRE_STRICT_FILE_CASES=1 python3 scripts/run_benchmarks.py ...`:
  VERIFIED; final GCC and Clang reports were generated for correction commit
  `817d65f22f6e8076602d9bcc5b23c2f25188bc0e` and contained executable hashes
  and normalized build evidence.
- `python3 tests/benchmark_metadata_tests.py`: VERIFIED; source-aware Intel
  pstate and generic boost polarity, fallback selection, missing probes, and
  unexpected values were tested without reading or changing host sysfs state.
- `python3 scripts/validate_benchmark_report.py ...`: VERIFIED.
- `python3 tests/benchmark_invariant_tests.py ...`: VERIFIED.
- `python3 scripts/render_benchmark_report.py ...`: VERIFIED.
- `python3 tests/benchmark_failure_tests.py`: VERIFIED.
- Clang benchmark-aware Release configure/build, CTest 18/18, benchmark
  generation, schema validation, invariants, and rendering: VERIFIED.

The host could not provide the Ubuntu package database, so dependency metadata
was recorded as unavailable with `dpkg-query` probe failure. Ubuntu CI uses the
actual installed package query. No timing threshold or speed claim was
introduced.

### Determinism, stress, and fuzz

- Two prescribed demo runs after the directory-creation correction: VERIFIED;
  JSON and Markdown compare byte-for-byte and match committed golden reports.
- `python3 tests/agent_investigation_demo_test.py --server
  ./build/release/native-mcp-sandbox`: VERIFIED, including forbidden-field
  negatives and missing-output-directory regression.
- `NMS_STRESS_ITERATIONS=20000 ./scripts/run_security_stress.sh`: VERIFIED;
  ASan/UBSan full CTest, deterministic fuzz smoke with seed `828927513140`, and
  g++ TSan orchestration tests passed. No crash, hang, sanitizer finding, or
  artifact was produced.
- `NMS_FUZZ_SECONDS=60 ./scripts/run_fuzz_campaign.sh`: VERIFIED; all five
  Clang libFuzzer targets completed their corpus and 60-second campaigns with
  no crash artifact. Captured final executed-unit counts were ELF 3,920,987,
  log 965,206, and process 2,953,471. Protocol and runtime-config totals were
  not recoverable from the bounded terminal capture and are therefore
  UNAVAILABLE, not guessed.

### Secret and generated-output audit

The following local searches were VERIFIED with no matches in tracked files,
history markers, or generated reports: `nvapi-`, `NVIDIA_API_KEY`,
`NIM_API_KEY`, bearer authorization headers, generic API-key assignments,
private-key headers, tracked `.env` contents, absolute temporary paths, raw
runtime PIDs/UIDs, addresses, memory-total fields, and current timestamps in
deterministic golden reports. No `.env.example` is currently committed;
`.gitignore` explicitly allows one with `!.env.example`.

No reputable local secret scanner (`gitleaks`, `trufflehog`, or
`detect-secrets`) was installed, so third-party scanner coverage is
UNAVAILABLE. No repository content was uploaded.

## External model-provider boundary and NIM readiness

ADR 0013 is sufficient as the Phase 10 architecture boundary. It requires a
separate provider-neutral client process with configurable endpoint/model,
secret-only API-key loading, no key in arguments, connect/read/total deadlines,
bounded request/response sizes, bounded retry/backoff, explicit 401/403/404/
408/429/5xx handling, malformed/truncated-stream handling, untrusted provider
output, closed-schema tool-call validation, exact advertised-tool allowlisting,
no raw paths/PIDs, no shell, deterministic local fake-provider tests, optional
manual synthetic live smoke, and redacted transcripts/exceptions.

No provider code, HTTP dependency, API key, credential, live call, or model
endpoint was added. The native server remained stdio-only, network-free, and
credential-free.

## Remaining limitations and Phase 10 gate

Verified local results apply only to the tested revisions, host, compilers,
tools, inputs, and bounded campaign durations. The host is not Ubuntu,
package-version metadata is unavailable locally, the local `gh` token is
invalid, and no immutable action pin/update process exists yet. These are recorded limitations rather than
claims of universal correctness, memory safety, race freedom, security, or
provider availability.

GitHub Actions evidence is maintained in the PR checks and PR body for the
actual pushed head. This audit document intentionally does not call any
embedded workflow run the final or exact-head run. The remaining local
limitations and the documented action-pinning follow-up do not block Phase 10
planning; they do not authorize Phase 10 implementation in this PR.

Phase 10 recommendation: **GO FOR PHASE 10 PLANNING**.
