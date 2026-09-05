# Releasing Native MCP Sandbox

Releases are evidence-bearing snapshots, not a substitute for ongoing verification. Tags are never rewritten or moved.

1. Select a version from the tag history, project version and the scope of the change. Record the rationale in `CHANGELOG.md`.
2. Update the authoritative project version, version-output expectations, deterministic demonstration metadata and current-version documentation. Preserve clearly labelled historical references.
3. Run the documented focused suites, development and release builds, sanitizer and ThreadSanitizer suites, deterministic fuzzing, libFuzzer smoke campaigns, documentation integrity checks and `git diff --check`.
4. Open a focused release PR. State whether native authority changed, record exact commands and results, and keep normal CI offline and credential-free.
5. Require CI for the exact PR head and a separate exact-head review. Resolve every blocker and repeat both after each push.
6. Merge only the reviewed head. Confirm the push-triggered `main` CI is green for the actual merge commit.
7. Create an annotated version tag on that exact green `main` commit. Verify both `git rev-parse <tag>` and `git rev-parse main` identify the intended commit, and verify `--version` from the tagged checkout.
8. Push the immutable tag. The release workflow validates version agreement, builds the native
   CPack archive and Python distributions, generates SPDX SBOMs and SHA-256 checksums, records
   GitHub build-provenance attestations, and publishes the GitHub Release.
9. Download the published assets, verify `SHA256SUMS`, then extract the native archive and run
   `--version` and `--self-check` from it.
10. From a clean checkout of the tag, follow the README literally: configure, build, run the normal
    test command, and run the deterministic offline demo. Verify the documented outputs and links.

The optional hosted-provider smoke is manual, synthetic-only, redacted and observational. It is never release evidence.
