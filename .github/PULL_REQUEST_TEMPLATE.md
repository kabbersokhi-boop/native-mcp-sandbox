## Summary

<!-- What changed, and why is this the smallest sufficient change? -->

## Scope

- [ ] Native C++ server
- [ ] Runtime policy
- [ ] External Python agent
- [ ] Provider adapter
- [ ] Tests / fuzzing
- [ ] Documentation only

## Security boundary

- [ ] No new shell, arbitrary path, raw PID, process-control or native-network authority
- [ ] Native server remains stdio-only and credential-free
- [ ] Provider output remains untrusted
- [ ] Tool proposals still require exact allowlist, closed-schema and local authorization
- [ ] MCP execution remains serial and at most once
- [ ] Normal CI remains offline and credential-free
- [ ] No credentials, private host evidence or absolute local paths are committed

<!-- Describe any changed assumption, authority boundary, resource limit, data-flow mode or residual risk. Write "None" when unchanged. -->

## Validation

<!-- Replace or remove commands that do not apply. Include exact counts and the tested head SHA. -->

```text
Head SHA:

Phase 10.4:
Phase 10.3:
Phase 10.2:
Phase 10.1 security:
Phase 10.1:

CTest dev:
CTest sanitizers:
CTest thread-sanitizer:

Deterministic fuzz:
libFuzzer:
git diff --check:
```

## Documentation

- [ ] README or public behavior is unchanged
- [ ] README / architecture / security / threat model updated as needed
- [ ] Changelog updated when the change is notable
- [ ] Examples contain no real credentials or private data

## Review notes

<!-- Point reviewers to the highest-risk files, invariants and negative tests. -->
