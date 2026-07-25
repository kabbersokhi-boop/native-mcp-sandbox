# Phase 9.5 independent release audit

Audit target: annotated tag `v0.10.0` and merge commit
`ee989929c490f72513c9cdf9b6180449059c4b65`.

This audit is a pre-Phase 10 checkpoint. It does not add an agent, a model
provider, networking, credentials, new MCP tools, or new host authority.

## Verified release evidence

GitHub Actions push run `30102197330` used `main` at the exact audit target.
All five jobs completed successfully:

- GCC / Debug
- Clang / Release
- AddressSanitizer and UndefinedBehaviorSanitizer with leak detection
- ThreadSanitizer orchestration stress
- bounded libFuzzer corpus and mutation smoke

Both compiler jobs built the Phase 9 benchmark target and passed report
generation, offline schema validation, invariant checks, Markdown rendering,
and bounded failure tests.

## Static findings

### Release version drift — high priority

The tagged release is `v0.10.0`, but three build or runtime sources still use
`0.9.0`:

- the CMake project version;
- `native_mcp::project_version()` and therefore `--version`;
- the foundation version assertion.

The README and security policy also describe an older release state. This is a
post-release consistency defect. It does not change the server security
boundary, but it must be corrected before Phase 10 work is merged.

The durable correction should make the CMake project version the single source
for the compiled version string and should add a CTest assertion for the actual
`native-mcp-sandbox --version` output.

### Benchmark environment metadata — medium priority

The report schema has explicit fields for compiler, build, dependency, CPU,
clock, and noise information. Unavailable values are represented honestly.
However:

- CI records `nlohmann-json3-dev` as `dependencyVersions` without the installed
  package version;
- compile and link flags are normally unavailable in CI;
- frequency governor, turbo state, and virtualization are not probed.

These are reproducibility-quality gaps. They do not invalidate the bounded
benchmark cases or the `v0.10.0` security boundary. A correction should capture
actual installed dependency versions and add read-only probes or explicit
build-command evidence without changing host state.

### Release documentation drift — medium priority

The README still identifies `v0.9.0` as the current release, uses a latest
GitHub Release badge even though `v0.10.0` is an annotated tag without a GitHub
Release object, and lists Phase 9 as unfinished. `SECURITY.md` also describes
`0.9.0` as a candidate.

The documentation should identify `v0.10.0` as the current supported tag, use a
tag-aware badge or create an intentionally reviewed GitHub Release, and show
Phases 0–9 as complete.

### Supply-chain hardening — review before implementation

The CI workflow grants read-only contents permission, which is appropriate. Its
third-party checkout action is referenced by a moving major tag. Pinning actions
to reviewed immutable commit SHAs would reduce workflow supply-chain drift, but
that change should be performed with an explicit update procedure rather than a
one-off unmaintained pin.

### Independent native execution — pending

This audit environment could inspect the repository and GitHub Actions evidence
but could not clone or compile the repository because direct GitHub network
resolution was unavailable. A clean-room native run is therefore still
required from a fresh checkout of `v0.10.0` and again after any correction.

## External model-provider boundary

A hosted model provider, including an NVIDIA NIM free development endpoint,
must be integrated through a separate agent/client process. The C++ MCP server
must remain local, stdio-based, credential-free, and network-free.

Hosted model output, tool-call suggestions, log text, and other evidence are
untrusted input. The agent must validate every proposed action against a closed
schema and the existing symbolic aliases. It must not convert model text into a
shell command, raw path, PID, network request from the server, or unsupported
MCP method.

Normal CI must use deterministic local model doubles and scripted adversarial
responses. A live hosted-provider smoke test may be manual or separately gated,
but it must not be required for merge, correctness, determinism, or release.
Free hosted endpoints can be throttled, changed, or removed.

API keys must come from an environment variable or a CI secret and must never
appear in command-line arguments, policy files, fixtures, reports, logs,
exceptions, recorded transcripts, or committed files.

## Phase 10 entry criteria

Do not start Phase 10 implementation until all of these conditions are met:

1. The release-version drift is corrected and tested.
2. README and security documentation identify `v0.10.0` consistently.
3. The benchmark metadata correction is reviewed and exact-head CI passes.
4. A clean-room GCC, Clang, sanitizer, ThreadSanitizer, benchmark, demonstration,
   and bounded fuzz campaign passes from the correction head.
5. A credential scan and generated-output scan find no secrets, host paths, raw
   PIDs, UIDs, addresses, or runtime timestamps in committed evidence.
6. The external model-client boundary is accepted as an architecture decision.
7. Phase 10 has a separate plan and pull request. No live provider is connected
   until deterministic mock-agent and malformed-provider tests pass.

## Non-claims

This review and the recorded finite test runs do not prove complete correctness,
memory safety, race freedom, security, provider availability, or model
reliability. They apply only to the inspected revision, workflows, and inputs.
