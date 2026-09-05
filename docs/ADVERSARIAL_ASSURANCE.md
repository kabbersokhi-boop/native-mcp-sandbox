# Adversarial Agent Assurance

This is an offline assurance campaign for the closed provider contracts and bounded stdio
orchestration. It adds no live
provider, credentials, native networking, tools, streaming, or parallel MCP
execution.

`tests/adversarial_agent_tests.py` uses only committed fake-provider/MCP fixtures and
deterministic process seams.  Its named classes cover hostile provider parsing,
evidence forgery, correlation and replay, multi-call stop behavior, failure and
retry taxonomy, unique secret sentinels, endpoint/redirect/TLS policy,
transcript tampering and determinism, budgets/deadlines/lifecycle, tool-surface
and authorization attacks, serial authority, and native-source scope guards.

## Review-blocker mapping

| Blocker | Named assurance | What is proved |
| --- | --- | --- |
| Stop after first rejected proposal | `MultipleCallStopTests.test_rejected_first_proposal_stops_later_valid_proposal_before_authority_or_write` | A locally rejected first proposal with a valid successor produces `proposal_rejected` plus deterministic `skipped`; the successor is never authorized, written as `tools/call`, assigned an MCP request ID, added to evidence, or added to execution order/completed state. Existing failure, timeout, and cancellation stop tests remain in `test_failure_timeout_and_cancellation_skip_later_proposals`. |
| Retry delay boundaries | `FailureTaxonomyTests.test_default_retry_backoff_and_remaining_time_boundaries_have_exact_delays`, `test_retry_after_and_attempt_budget_boundaries_have_exact_delays`, and `test_permanent_deadline_and_exhausted_retries_are_ineligible_with_zero_delay` | The exhaustive `FailureClass` retryability matrix is retained, with exact default backoff, bounded Retry-After, equality/one-over remaining time, final attempt/one-over attempt, permanent failure, exhausted attempts, and exhausted deadline delay values asserted. |
| Unique secret sentinels through real surfaces | `SecretSentinelTests.test_unique_sentinels_cross_real_child_stream_result_error_and_argv_boundaries_without_project_leakage` and `test_report_and_crash_artifact_surfaces_do_not_exist_in_agent_modules` | The same unique campaign values traverse a fixture's stdout JSON-RPC result, stderr, and MCP error result; child environment, actual constructed argv, retained stdout/stderr buffers, exception/failure paths, evidence, and transcript contain none. No deterministic summary, report, or crash-artifact surface exists in the bounded agent modules; the structural assertion protects that statement. |
| Transcript/provenance/boundary assurance | `TranscriptTamperTests.test_transcript_unknown_event_metadata_schema_version_limited_and_object_tampering_fail_closed`, `test_transcript_exact_prefix_terminal_immutability_serialized_append_and_repeat_are_closed`, `ProvenanceReferenceAttackTests.test_nonexistent_response_forged_action_mismatch_and_provider_manufactured_evidence_never_cross_authority`, `BudgetDeadlineLifecycleTests.test_explicit_provider_and_mcp_request_response_byte_exact_and_one_over_boundaries`, and `test_provider_turn_calls_per_turn_and_total_call_exact_and_one_over_boundaries` | Unknown events, wrong/missing/extra/type-invalid metadata, unknown top-level fields, schema/limited/event-object corruption, serialized terminal append, forged/stale action identity, fabricated response reference, provider-manufactured evidence, exact/one-over provider and MCP bytes, transcript terminal capacity, provider turns, calls/turn, and total calls all fail closed at their stated boundary. |
| Transcript action/response provenance correlation | `ProvenanceReferenceAttackTests.test_transcript_orphan_mcp_response_and_orphan_evidence_validation_fail_closed`, `test_transcript_existing_action_wrong_response_and_existing_response_wrong_action_fail_closed`, `test_transcript_nonexistent_response_999_and_duplicate_stale_evidence_fail_closed`, and `test_valid_generated_transcript_still_parses_and_is_byte_identical` | The bounded parser-local lifecycle pass requires `authorized` → `mcp_request` → matching `mcp_response` → one matching `evidence_validated`; orphan, nonexistent, mismatched, duplicate, and stale action/response references fail closed while valid generated transcripts and transcript-limit accepted prefixes remain deterministic. |

The retained authority boundaries are unchanged: provider text never creates
validated evidence; evidence is produced only from a locally authorized,
correlated MCP response; one active call is enforced; child environment and
diagnostics are scrubbed before becoming owned outputs; transcripts use a
closed schema and an immutable terminal prefix; and all test seams remain
offline and deterministic.

The campaign preserves the existing closed schemas, local provenance-only
evidence creation, one-active-call rule, deadline-dominated shutdown, scrubbed
child environment, redaction primitives, and credential-free normal CI.  It
does not claim that finite tests or fuzzing prove absence of all defects.
