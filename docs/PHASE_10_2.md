# Phase 10.2: bounded offline MCP orchestration

Phase 10.2 is an offline Python orchestration layer.  It does not alter the
native C++ server, add network access, credentials, streaming, new tools, or
parallel MCP calls.

Every run owns one child lifecycle.  A monotonic absolute deadline supplies the
remaining budget to startup, initialize, initialized notification, tools/list,
provider turns, calls, cancellation, and shutdown.  The child gets a newly
constructed Phase 10.1 allowlisted environment and starts with `shell=False`.
`run()` always closes stdin and performs bounded terminate/kill/reap cleanup.
Every blocking terminate, kill, and reap wait is derived solely from positive
remaining absolute orchestration time: graceful termination is capped by both
its configured limit and that remainder, and a kill/reap wait gets only the
subsequent positive remainder.  Total expiry creates no new cleanup wait lease.
After expiry the client may send non-blocking safety signals and make only a
zero-time reap check, but it does not block again; an unreaped child is recorded deterministically as
`shutdown_unreaped`, never as successful cleanup.
`subprocess.Popen` is the trusted local creation primitive (the standard
library cannot asynchronously preempt it); `process_startup_timeout_ms` bounds
the first enforceable readiness boundary, the correlated `initialize` response,
as well as being dominated by the total deadline.

The client accepts one outstanding JSON-RPC request.  It rejects malformed or
duplicate-key JSON, incomplete EOF records, unsolicited/future/duplicate IDs,
unknown closed-contract fields, and cumulative stdout/stderr or message limits.
It captures an immutable canonical tool surface and can narrowly revalidate a
second `tools/list` response for an identity change.

Provider turns use an explicit bounded `ProviderTurn.turn(..., timeout_ms,
cancellation)` interface.  The request is serialized and bounded before the
turn, expiry is checked immediately after it, and no proposal can be authorized
after expiry.  Cancellation is checked before every lifecycle wait and action.
The bundled `ScriptedProvider` is the only supported deterministic Phase 10.2 provider: delayed
scripts poll cancellation and convert an over-budget delay to a local timeout;
it never starts a detached worker or continues after returning.

Only `AuthorizedMcpAction` reaches the final execution boundary.  It binds the
surface hash, local content/context action identity, advertised name, frozen
arguments, and canonical argument bytes.  The client revalidates all of these
immediately before locally constructing the only permitted method: `tools/call`.

`tools/call` responses become evidence only after a closed result-envelope and
text-content validation.  Result text is structurally redacted with Phase 10.1
helpers before frozen evidence is made available to a later provider turn.

The Phase 10.2 transcript extends the Phase 10.1 transcript module with a
closed schema-version-2 control record.  It records lifecycle, surface,
provider, authorization, response, failure, skip, and outcome events without
raw child output or result bodies.  It accounts incrementally for bytes and
adds one deterministic terminal transcript-limit event rather than replacing
the complete history. Terminal space is reserved before ordinary control events
are accepted, so exhaustion never removes an accepted lifecycle event.

The deterministic stdio fixture has only synthetic in-process behavior.  It
includes malformed JSON/duplicate IDs/output flood, changed surface, delay,
ambiguous exit, malformed results, secret/path/PID text, and ignored-shutdown
cases.  These remain Phase 10.2 tests, not Phase 10.3 assurance or Phase 10.4
provider functionality.
