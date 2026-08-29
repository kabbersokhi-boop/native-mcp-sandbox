#!/usr/bin/env python3
"""adversarial assurance deterministic adversarial assurance for provider contracts/10.2."""

from __future__ import annotations

from dataclasses import replace
import json
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
from agent.native_mcp_agent.contracts import (
    AdvertisedTool,
    EvidenceProvenance,
    MessageRole,
    ProviderFinalMessage,
    ProviderMessage,
    ProviderRequest,
    ProviderToolCallProposal,
    RequestCorrelationId,
    ToolCallId,
    parse_closed_json,
    parse_provider_response,
)
from agent.native_mcp_agent.endpoint_policy import (
    ValidatedEndpoint,
    redirect_rejection,
    validate_fake_loopback_endpoint,
    validate_production_endpoint,
)
from agent.native_mcp_agent.environment import build_child_environment
from agent.native_mcp_agent.errors import (
    FailureClass,
    ProviderError,
    failure,
    http_failure,
)
from agent.native_mcp_agent.limits import DEFAULT_LIMITS
from agent.native_mcp_agent.mcp_orchestrator import (
    AuthorizedMcpAction,
    CancellationToken,
    Deadline,
    Evidence,
    McpStdioClient,
    Orchestrator,
    ScriptedProvider,
    capture_tool_surface,
)
from agent.native_mcp_agent.redaction import (
    redact_exception,
    redact_headers,
    redact_json,
    redact_provider_excerpt,
    redact_text,
)
from agent.native_mcp_agent.retry import decide_retry
from agent.native_mcp_agent.transcript import (
    BoundedTranscript,
    TranscriptEvent,
    parse_bounded_transcript,
    parse_transcript,
)
from agent.native_mcp_agent.transport import LoopbackFakeTransport

CHILD = os.path.join(ROOT, "tests", "fake_mcp_stdio_child.py")
SENTINELS = (
    "API_KEY_ASSURANCE_UNIQUE",
    "Authorization: Bearer TOKEN_ASSURANCE_UNIQUE",
    "proxy://user:pass@host",
    "SECRET_STORE_ASSURANCE_UNIQUE",
    "/absolute/agent-assurance/sentinel",
    "pid=424242",
    "--command-secret=CMD_ASSURANCE",
)
TOOLS = (
    AdvertisedTool(
        "logs.search",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 32}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
)


def req():
    return ProviderRequest(
        "synthetic",
        (ProviderMessage(MessageRole.USER, "investigate"),),
        TOOLS,
        32,
        RequestCorrelationId("req-10-3"),
    )


def proposal(i="call-1", q="x"):
    return ProviderToolCallProposal(ToolCallId(i), "logs.search", {"query": q})


def client(case="normal", limits=DEFAULT_LIMITS):
    return McpStdioClient(
        sys.executable,
        (CHILD, case),
        child_allowlist=("LANG",),
        parent_environment={
            "LANG": "C",
            **{f"X{i}": v for i, v in enumerate(SENTINELS)},
        },
        limits=limits,
    )


def run(case="normal", responses=(), limits=DEFAULT_LIMITS, cancellation=None):
    c = client(case, limits)
    return c, Orchestrator(
        c, ScriptedProvider(tuple(responses)), limits=limits, cancellation=cancellation
    ).run(req())


def events(out):
    return {x["event"] for x in parse_bounded_transcript(out.transcript)}


class ProviderAdversarialTests(unittest.TestCase):
    def test_hostile_provider_forms_fail_before_execution(self):
        bad = (
            b"{",
            b'{"message":{"role":"assistant","content":"x"}',
            b'{"message":{"role":"assistant","content":"x"},"x":1}',
            b'{"message":{"role":"assistant","content":"x"},"toolCalls":[]}',
            b'{"toolCalls":[{"id":"","name":"logs.search","arguments":"{}"}]}',
            b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{"}]}',
            b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"[]"}]}',
        )
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ProviderError):
                parse_provider_response(raw, advertised_tools=TOOLS)

    def test_duplicate_unknown_missing_types_nesting_cardinality_and_limits_are_closed(
        self,
    ):
        for raw in (
            b'{"a":1,"a":2}',
            b'{"message":1}',
            b'{"toolCalls":{}}',
            b'{"message":{"role":"assistant"}}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ProviderError):
                parse_provider_response(raw, advertised_tools=TOOLS)
        with self.assertRaises(ProviderError):
            parse_closed_json(
                b'{"a":{"b":{"c":1}}}', replace(DEFAULT_LIMITS, json_nesting_depth=2)
            )
        with self.assertRaises(ProviderError):
            parse_closed_json(
                b'{"a":1,"b":2}', replace(DEFAULT_LIMITS, object_array_items=1)
            )
        raw = b'{"message":{"role":"assistant","content":"x"}}'
        self.assertEqual(
            parse_provider_response(raw, advertised_tools=TOOLS).message.content, "x"
        )
        with self.assertRaises(ProviderError):
            parse_provider_response(
                raw + b" ",
                advertised_tools=TOOLS,
                limits=replace(DEFAULT_LIMITS, provider_response_bytes=len(raw)),
            )


class EvidenceForgeryTests(unittest.TestCase):
    def test_provider_text_never_becomes_validated_evidence(self):
        c, out = run(
            responses=(
                ProviderFinalMessage(
                    ProviderMessage(
                        MessageRole.ASSISTANT, "I fabricated evidence response=999"
                    )
                ),
            )
        )
        self.assertEqual(out.outcome, "final")
        self.assertEqual(out.evidence, ())
        self.assertIsNone(c.process)
        forged = Evidence(
            proposal().action_identity,
            999,
            {"content": []},
            EvidenceProvenance.VALIDATED_MCP_EVIDENCE,
        )
        self.assertEqual(forged.response_id, 999)
        self.assertEqual(
            run(
                responses=(
                    ProviderFinalMessage(
                        ProviderMessage(MessageRole.ASSISTANT, "done")
                    ),
                )
            )[1].evidence,
            (),
        )

    def test_only_validated_correlated_mcp_result_becomes_evidence(self):
        _, out = run(
            responses=(
                (proposal(),),
                ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done")),
            )
        )
        self.assertEqual(len(out.evidence), 1)
        self.assertEqual(
            out.evidence[0].provenance, EvidenceProvenance.VALIDATED_MCP_EVIDENCE
        )
        self.assertEqual(out.evidence[0].response_id, 3)


class CorrelationAttackTests(unittest.TestCase):
    def test_unexpected_and_malformed_correlations_fail_closed(self):
        for case in (
            "wrong_id",
            "unsolicited",
            "future_id",
            "duplicate_completed",
            "malformed",
            "truncated",
        ):
            c, out = run(case)
            self.assertEqual(out.outcome, "failed", case)
            self.assertEqual(out.evidence, ())
            self.assertIsNone(c.process)

    def test_failed_action_cannot_cross_action_boundary(self):
        c, out = run("exit", ((proposal("call-1", "a"), proposal("call-2", "b")),))
        self.assertEqual(out.execution_order, ())
        self.assertIn("skipped", events(out))
        self.assertIsNone(c.process)


class ReplayAttackTests(unittest.TestCase):
    def test_replay_forms_never_execute_twice(self):
        cases = (
            ((proposal("call-1"), proposal("call-1")),),
            ((proposal("call-1", "a"), proposal("call-1", "b")),),
            ((proposal("call-1", "a"), proposal("call-2", "a")),),
            ((proposal("call-1"),), (proposal("call-1"),)),
        )
        for replies in cases:
            _, out = run(responses=replies)
            self.assertEqual(len(out.execution_order), 0 if len(replies) == 1 else 1)
            self.assertEqual(out.outcome, "duplicate")

    def test_ambiguous_completion_does_not_retry_execution(self):
        _, out = run("exit", ((proposal(),),))
        self.assertEqual(out.execution_order, ())
        self.assertEqual(out.evidence, ())


class MultipleCallStopTests(unittest.TestCase):
    def test_rejected_first_proposal_stops_later_valid_proposal_before_authority_or_write(
        self,
    ):
        c = client()
        authorized = []
        original = c.authorize

        def observe(*args, **kwargs):
            authorized.append(args[1])
            return original(*args, **kwargs)

        c.authorize = observe
        rejected = proposal("call-rejected", "x" * 33)
        later = proposal("call-valid", "ok")
        out = Orchestrator(c, ScriptedProvider(((rejected, later),))).run(req())
        self.assertEqual(out.outcome, "rejected")
        self.assertEqual(authorized, [])
        self.assertEqual(
            c.next_id, 3, "later proposal must not consume a tools/call request ID"
        )
        self.assertEqual(out.evidence, ())
        self.assertEqual(out.execution_order, ())
        parsed = parse_bounded_transcript(out.transcript)
        self.assertIn(
            {
                "event": "proposal_rejected",
                "metadata": {"proposal": str(rejected.call_id)},
            },
            parsed,
        )
        self.assertIn(
            {"event": "skipped", "metadata": {"proposal": str(later.call_id)}}, parsed
        )

    def test_failure_timeout_and_cancellation_skip_later_proposals(self):
        for case, limits in (
            ("malformed_result", DEFAULT_LIMITS),
            ("delay", replace(DEFAULT_LIMITS, mcp_call_timeout_ms=20)),
        ):
            _, out = run(
                case, ((proposal("call-1", "a"), proposal("call-2", "b")),), limits
            )
            self.assertEqual(len(out.execution_order), 0)
            self.assertIn("skipped", events(out))
        token = CancellationToken()
        t = threading.Thread(target=lambda: (time.sleep(0.08), token.cancel()))
        t.start()
        _, out = run(
            "delay",
            ((proposal("call-1", "a"), proposal("call-2", "b")),),
            cancellation=token,
        )
        t.join()
        self.assertEqual(out.outcome, "cancelled")
        self.assertIn("skipped", events(out))


class FailureTaxonomyTests(unittest.TestCase):
    def test_every_failure_class_has_exact_retry_contract(self):
        retryable = {
            FailureClass.HTTP_408_REQUEST_TIMEOUT,
            FailureClass.HTTP_429_RATE_LIMITED,
            FailureClass.DNS_OR_CONNECTION_FAILURE,
            FailureClass.CONNECT_TIMEOUT,
            FailureClass.TRANSIENT_5XX,
        }
        for kind in FailureClass:
            decision = decide_retry(
                failure(kind),
                completed_attempts=0,
                remaining_ms=1000,
                limits=DEFAULT_LIMITS,
            )
            self.assertEqual(decision.eligible, kind in retryable, kind)
        self.assertFalse(
            decide_retry(
                failure(FailureClass.HTTP_429_RATE_LIMITED),
                completed_attempts=DEFAULT_LIMITS.provider_attempt_count,
                remaining_ms=1000,
                limits=DEFAULT_LIMITS,
            ).eligible
        )
        self.assertFalse(
            decide_retry(
                failure(FailureClass.HTTP_429_RATE_LIMITED, retry_after_ms=1000),
                completed_attempts=0,
                remaining_ms=999,
                limits=DEFAULT_LIMITS,
            ).eligible
        )
        self.assertFalse(
            decide_retry(
                http_failure(400),
                completed_attempts=0,
                remaining_ms=1000,
                limits=DEFAULT_LIMITS,
            ).eligible
        )

    def test_default_retry_backoff_and_remaining_time_boundaries_have_exact_delays(
        self,
    ):
        limits = replace(
            DEFAULT_LIMITS,
            provider_attempt_count=3,
            retry_backoff_ms=50,
            retry_after_ms=1000,
        )
        classified = failure(FailureClass.TRANSIENT_5XX)
        for remaining, eligible, delay in (
            (50, True, 50),
            (49, False, 0),
            (1000, True, 50),
        ):
            decision = decide_retry(
                classified, completed_attempts=0, remaining_ms=remaining, limits=limits
            )
            self.assertEqual((decision.eligible, decision.delay_ms), (eligible, delay))

    def test_retry_after_and_attempt_budget_boundaries_have_exact_delays(self):
        limits = replace(
            DEFAULT_LIMITS,
            provider_attempt_count=3,
            retry_backoff_ms=50,
            retry_after_ms=1000,
        )
        rate = failure(FailureClass.HTTP_429_RATE_LIMITED, retry_after_ms=75)
        for completed, remaining, eligible, delay in (
            (0, 75, True, 75),
            (0, 74, False, 0),
            (2, 1000, True, 75),
            (3, 1000, False, 0),
        ):
            decision = decide_retry(
                rate,
                completed_attempts=completed,
                remaining_ms=remaining,
                limits=limits,
            )
            self.assertEqual((decision.eligible, decision.delay_ms), (eligible, delay))

    def test_permanent_deadline_and_exhausted_retries_are_ineligible_with_zero_delay(
        self,
    ):
        for classified, completed, remaining in (
            (failure(FailureClass.HTTP_400_INVALID_REQUEST), 0, 1000),
            (
                failure(FailureClass.TRANSIENT_5XX),
                DEFAULT_LIMITS.provider_attempt_count,
                1000,
            ),
            (failure(FailureClass.TRANSIENT_5XX), 0, 0),
        ):
            decision = decide_retry(
                classified,
                completed_attempts=completed,
                remaining_ms=remaining,
                limits=DEFAULT_LIMITS,
            )
            self.assertEqual((decision.eligible, decision.delay_ms), (False, 0))


class SecretSentinelTests(unittest.TestCase):
    def test_unique_sentinels_are_absent_from_every_project_output_boundary(self):
        parent = {"LANG": "C", **{f"SECRET_{i}": v for i, v in enumerate(SENTINELS)}}
        env = build_child_environment(parent, ("LANG",))
        surfaces = [
            str(env),
            redact_text(" ".join(SENTINELS), SENTINELS),
            str(
                redact_headers(
                    {"Authorization": SENTINELS[1], "x": SENTINELS[0]}, SENTINELS
                )
            ),
            str(redact_json({"diagnostic": " ".join(SENTINELS)}, SENTINELS)),
            redact_exception(Exception(" ".join(SENTINELS)), SENTINELS),
            redact_provider_excerpt(" ".join(SENTINELS), SENTINELS),
        ]
        c, out = run("secret_result", ((proposal(),),))
        surfaces.extend(
            (str(c.environment), str(out.evidence), out.transcript.decode())
        )
        for sentinel in SENTINELS:
            self.assertTrue(
                all(sentinel not in surface for surface in surfaces), sentinel
            )

    def test_unique_sentinels_cross_real_child_stream_result_error_and_argv_boundaries_without_project_leakage(
        self,
    ):
        c, out = run("unique_secret_output", ((proposal(),),))
        error_client, error_out = run("unique_secret_error", ((proposal(),),))
        parent = {
            "LANG": "C",
            **{f"SECRET_{i}": value for i, value in enumerate(SENTINELS)},
        }
        surfaces = (
            str(build_child_environment(parent, ("LANG",))),
            str(c.environment),
            str(c.arguments),
            str([c.executable, *c.arguments]),
            c.out.decode("utf-8", "replace"),
            c.err.decode("utf-8", "replace"),
            str(out.evidence),
            out.transcript.decode(),
            str(error_out.evidence),
            error_out.transcript.decode(),
            str(error_client.err),
            redact_exception(Exception(" ".join(SENTINELS)), SENTINELS),
            redact_text(" ".join(SENTINELS), SENTINELS),
        )
        self.assertEqual(out.outcome, "failed")
        self.assertEqual(error_out.outcome, "failed")
        self.assertEqual(c.next_id, 4)
        for sentinel in SENTINELS:
            self.assertTrue(all(sentinel not in value for value in surfaces), sentinel)

    def test_report_and_crash_artifact_surfaces_do_not_exist_in_agent_modules(self):
        owned = [
            path
            for path in Path(ROOT, "agent", "native_mcp_agent").iterdir()
            if path.suffix == ".py"
        ]
        self.assertFalse(
            any("report" in path.name or "crash" in path.name for path in owned)
        )


class EndpointPolicyAdversarialTests(unittest.TestCase):
    def test_insecure_userinfo_fragment_tls_redirect_and_destination_attacks_fail(self):
        for url in (
            "http://example/x",
            "https://u:p@example/x",
            "https://example/x#f",
            "https:///x",
            "ftp://example/x",
        ):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                validate_production_endpoint(url)
        with self.assertRaises(ProviderError):
            validate_production_endpoint("https://example/x", verify_tls=False)
        self.assertEqual(
            redirect_rejection("https://evil").classification,
            FailureClass.REDIRECT_REJECTED,
        )

        def private(*_):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 1))]

        with self.assertRaises(ProviderError):
            validate_fake_loopback_endpoint(
                "http://localhost:1/x", allow_loopback_http=True, resolver=private
            )

    def test_transport_forged_authority_never_connects(self):
        calls = []
        t = LoopbackFakeTransport(connection_factory=lambda *x: calls.append(x))
        with self.assertRaises(ProviderError):
            t.send(
                ValidatedEndpoint(
                    "http://127.0.0.1:1/x",
                    "http",
                    "127.0.0.1",
                    "10.0.0.1",
                    1,
                    "/x",
                    True,
                ),
                req(),
                correlation_id="req-10-3",
            )
        self.assertEqual(calls, [])


class TranscriptTamperTests(unittest.TestCase):
    def test_closed_transcript_and_limit_tampering_fail(self):
        raw = TranscriptEvent(
            "event",
            "adapter",
            "model",
            RequestCorrelationId("req-10-3"),
            EvidenceProvenance.LOCAL_CONTROL_EVENT,
            metadata={"mode": "safe"},
        ).to_json_bytes()
        for mutate in (
            b'{"schemaVersion":1}',
            raw[:-1] + b',"x":1}',
            raw.replace(b'"schemaVersion":1', b'"schemaVersion":2'),
        ):
            with self.subTest(mutate=mutate), self.assertRaises(ProviderError):
                parse_transcript(mutate)
        limited = BoundedTranscript(replace(DEFAULT_LIMITS, transcript_bytes=150))
        limited.add("process_start")
        limited.add("initialize_request")
        data = limited.to_json_bytes()
        parsed = parse_bounded_transcript(data)
        self.assertEqual(sum(x["event"] == "transcript_limit" for x in parsed), 1)

    def test_repeated_project_outputs_are_byte_identical(self):
        a = run(
            responses=(
                ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done")),
            )
        )[1].transcript
        b = run(
            responses=(
                ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done")),
            )
        )[1].transcript
        self.assertEqual(a, b)

    def test_transcript_unknown_event_metadata_schema_version_limited_and_object_tampering_fail_closed(
        self,
    ):
        valid = {
            "schemaVersion": 2,
            "events": [
                {
                    "event": "provider_turn_start",
                    "metadata": {"turn": "0", "bytes": "1"},
                }
            ],
            "limited": False,
        }
        mutations = []
        for event, metadata in (
            ("unknown", {}),
            ("provider_turn_start", {"turn": "0"}),
            ("provider_turn_start", {"turn": "0", "bytes": "1", "extra": "x"}),
            ("provider_turn_start", {"turn": 0, "bytes": "1"}),
        ):
            mutations.append(
                {**valid, "events": [{"event": event, "metadata": metadata}]}
            )
        mutations.extend(
            (
                {**valid, "unknown": True},
                {**valid, "schemaVersion": 3},
                {**valid, "limited": 1},
                {**valid, "events": ["not-an-event"]},
            )
        )
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ProviderError):
                parse_bounded_transcript(
                    json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
                )

    def test_transcript_exact_prefix_terminal_immutability_serialized_append_and_repeat_are_closed(
        self,
    ):
        seed = BoundedTranscript()
        seed.add("process_start")
        seed.add("initialize_request")
        exact_limit = len(seed.to_json_bytes()) + len(
            b'{"events":[],"limited":true,"schemaVersion":2}'
        )
        transcript = BoundedTranscript(
            replace(DEFAULT_LIMITS, transcript_bytes=exact_limit)
        )
        transcript.add("process_start")
        transcript.add("initialize_request")
        prefix = parse_bounded_transcript(transcript.to_json_bytes())
        transcript.add("initialized_notification")
        exhausted = transcript.to_json_bytes()
        parsed = parse_bounded_transcript(exhausted)
        self.assertEqual(parsed[:-1], prefix)
        self.assertEqual(parsed[-1]["event"], "transcript_limit")
        self.assertEqual(sum(x["event"] == "transcript_limit" for x in parsed), 1)
        transcript.add("tools_list_request")
        self.assertEqual(transcript.to_json_bytes(), exhausted)
        appended = json.loads(exhausted)
        appended["events"].append({"event": "shutdown_start", "metadata": {}})
        with self.assertRaises(ProviderError):
            parse_bounded_transcript(
                json.dumps(appended, separators=(",", ":"), sort_keys=True).encode()
            )


class BudgetDeadlineLifecycleTests(unittest.TestCase):
    def test_budget_exact_one_over_and_lifecycle_edges_fail_closed(self):
        raw = b'{"x":1}'
        self.assertEqual(
            parse_closed_json(
                raw, replace(DEFAULT_LIMITS, provider_response_bytes=len(raw))
            ),
            {"x": 1},
        )
        with self.assertRaises(ProviderError):
            parse_closed_json(
                raw, replace(DEFAULT_LIMITS, provider_response_bytes=len(raw) - 1)
            )
        for case in ("oversized", "flood", "truncated", "exit"):
            c, out = run(case)
            self.assertEqual(out.outcome, "failed")
            self.assertIsNone(c.process)

    def test_expiry_cancellation_and_shutdown_have_no_later_authority(self):
        limits = replace(
            DEFAULT_LIMITS, orchestration_total_timeout_ms=30, mcp_call_timeout_ms=500
        )
        c, out = run("delay", ((proposal("call-1"), proposal("call-2")),), limits)
        self.assertEqual(out.evidence, ())
        self.assertIsNone(c.process)
        c = client(
            "ignore_shutdown", replace(DEFAULT_LIMITS, graceful_shutdown_timeout_ms=10)
        )
        d = Deadline(c.clock() + 1, c.clock)
        c.initialize_and_capture(d)
        self.assertEqual(c.close(d, suppress=True), "kill")

    def test_explicit_provider_and_mcp_request_response_byte_exact_and_one_over_boundaries(
        self,
    ):
        provider_bytes = req().to_json_bytes()
        self.assertEqual(
            req().to_json_bytes(
                replace(DEFAULT_LIMITS, provider_request_bytes=len(provider_bytes))
            ),
            provider_bytes,
        )
        with self.assertRaises(ProviderError):
            req().to_json_bytes(
                replace(DEFAULT_LIMITS, provider_request_bytes=len(provider_bytes) - 1)
            )
        response = ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done"))
        provider_response = len(
            json.dumps(
                {"kind": "final", "role": "assistant", "content": "done"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        )
        self.assertEqual(
            run(
                responses=(response,),
                limits=replace(
                    DEFAULT_LIMITS, provider_response_bytes=provider_response
                ),
            )[1].outcome,
            "final",
        )
        self.assertEqual(
            run(
                responses=(response,),
                limits=replace(
                    DEFAULT_LIMITS, provider_response_bytes=provider_response - 1
                ),
            )[1].outcome,
            "failed",
        )
        for field, delta in (
            ("mcp_request_bytes", 0),
            ("mcp_request_bytes", -1),
            ("mcp_response_bytes", 0),
            ("mcp_response_bytes", -1),
        ):
            c = client()
            d = Deadline(c.clock() + 5, c.clock)
            c.initialize_and_capture(d)
            action = c.authorize(
                proposal().action_identity, "call-1", "logs.search", {"query": "x"}
            )
            request_raw = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "logs.search", "arguments": {"query": "x"}},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            response_raw = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": '{"message":"synthetic"}',
                            }
                        ],
                        "isError": False,
                        "structuredContent": {"message": "synthetic"},
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            c.limits = replace(
                c.limits,
                **{
                    field: len(request_raw) + delta
                    if field == "mcp_request_bytes"
                    else len(response_raw) + delta
                },
            )
            if delta == 0:
                self.assertEqual(c.execute(action, d).request_id, 3)
            else:
                with self.assertRaises(ProviderError):
                    c.execute(action, d)
            c.close(d, suppress=True)

    def test_provider_turn_calls_per_turn_and_total_call_exact_and_one_over_boundaries(
        self,
    ):
        final = ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done"))
        self.assertEqual(
            run(
                responses=(final,),
                limits=replace(DEFAULT_LIMITS, provider_turn_count=1),
            )[1].outcome,
            "final",
        )
        self.assertEqual(
            run(
                responses=((proposal(),), final),
                limits=replace(DEFAULT_LIMITS, provider_turn_count=1),
            )[1].outcome,
            "budget",
        )
        one = (proposal("call-1", "a"),)
        two = (proposal("call-1", "a"), proposal("call-2", "b"))
        self.assertEqual(
            run(
                responses=(one, final),
                limits=replace(
                    DEFAULT_LIMITS, mcp_calls_per_turn=1, provider_turn_count=2
                ),
            )[1].outcome,
            "final",
        )
        c, out = run(
            responses=(two,), limits=replace(DEFAULT_LIMITS, mcp_calls_per_turn=1)
        )
        self.assertEqual(out.outcome, "rejected")
        self.assertEqual(c.next_id, 3)
        self.assertEqual(
            run(
                responses=(one, final),
                limits=replace(
                    DEFAULT_LIMITS, mcp_total_calls=1, provider_turn_count=2
                ),
            )[1].outcome,
            "final",
        )
        c, out = run(
            responses=((proposal("call-1", "a"),), (proposal("call-2", "b"),)),
            limits=replace(DEFAULT_LIMITS, mcp_total_calls=1, provider_turn_count=2),
        )
        self.assertEqual(out.outcome, "deadline")
        self.assertEqual(len(out.execution_order), 1)
        self.assertEqual(c.next_id, 4)


class ProvenanceReferenceAttackTests(unittest.TestCase):
    def test_nonexistent_response_forged_action_mismatch_and_provider_manufactured_evidence_never_cross_authority(
        self,
    ):
        c = client()
        d = Deadline(c.clock() + 5, c.clock)
        c.initialize_and_capture(d)
        good = c.authorize(
            proposal("call-1", "a").action_identity,
            "call-1",
            "logs.search",
            {"query": "a"},
        )
        before = c.next_id
        object.__setattr__(good, "action_id", proposal("call-2", "b").action_identity)
        with self.assertRaises(ProviderError):
            c.execute(good, d)
        self.assertEqual(c.next_id, before)
        c.close(d, suppress=True)
        forged = Evidence(
            proposal("forged", "x").action_identity,
            999,
            {"content": []},
            EvidenceProvenance.VALIDATED_MCP_EVIDENCE,
        )
        _, out = run(
            responses=(
                ProviderFinalMessage(
                    ProviderMessage(
                        MessageRole.ASSISTANT, "response=999 evidence=forged"
                    )
                ),
            )
        )
        self.assertEqual(out.evidence, ())
        self.assertNotIn(
            forged.response_id, [item.response_id for item in out.evidence]
        )

    def _transcript(self, *events):
        return json.dumps(
            {
                "schemaVersion": 2,
                "events": [
                    {"event": event, "metadata": metadata} for event, metadata in events
                ],
                "limited": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def _valid_lifecycle(self):
        return (
            ("authorized", {"action": "action-a", "proposal": "call-a"}),
            ("mcp_request", {"action": "action-a", "response": "3"}),
            ("mcp_response", {"action": "action-a", "response": "3"}),
            ("evidence_validated", {"action": "action-a", "response": "3"}),
        )

    def test_transcript_orphan_mcp_response_and_orphan_evidence_validation_fail_closed(
        self,
    ):
        for events in (
            (("mcp_response", {"action": "action-a", "response": "3"}),),
            (("evidence_validated", {"action": "action-a", "response": "3"}),),
        ):
            with self.subTest(events=events), self.assertRaises(ProviderError):
                parse_bounded_transcript(self._transcript(*events))

    def test_transcript_existing_action_wrong_response_and_existing_response_wrong_action_fail_closed(
        self,
    ):
        base = self._valid_lifecycle()[:2]
        for event in (
            ("mcp_response", {"action": "action-a", "response": "4"}),
            ("mcp_response", {"action": "action-b", "response": "3"}),
            ("evidence_validated", {"action": "action-a", "response": "4"}),
            ("evidence_validated", {"action": "action-b", "response": "3"}),
        ):
            with self.subTest(event=event), self.assertRaises(ProviderError):
                parse_bounded_transcript(self._transcript(*base, event))

    def test_transcript_nonexistent_response_999_and_duplicate_stale_evidence_fail_closed(
        self,
    ):
        base = self._valid_lifecycle()
        for events in (
            base[:2] + (("mcp_response", {"action": "action-a", "response": "999"}),),
            base + (("evidence_validated", {"action": "action-a", "response": "3"}),),
        ):
            with self.subTest(events=events), self.assertRaises(ProviderError):
                parse_bounded_transcript(self._transcript(*events))

    def test_valid_generated_transcript_still_parses_and_is_byte_identical(self):
        a = run(
            responses=(
                (proposal(),),
                ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done")),
            )
        )[1].transcript
        b = run(
            responses=(
                (proposal(),),
                ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done")),
            )
        )[1].transcript
        self.assertEqual(a, b)
        self.assertTrue(parse_bounded_transcript(a))


class ToolSurfaceAuthorizationSerialScopeTests(unittest.TestCase):
    def test_tool_surface_and_forged_authorization_are_rejected_before_write(self):
        bad = (
            {
                "tools": [
                    {
                        "name": "x",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                            "additionalProperties": False,
                        },
                    },
                    {
                        "name": "x",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                            "additionalProperties": False,
                        },
                    },
                ]
            },
            {"tools": [{"name": "x", "inputSchema": {}}]},
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ProviderError):
                capture_tool_surface(value)
        c = client()
        d = Deadline(c.clock() + 1, c.clock)
        surface = c.initialize_and_capture(d)
        before = c.next_id
        forged = AuthorizedMcpAction(
            surface.identity,
            proposal().action_identity,
            "call-1",
            "logs.search",
            {"query": "x"},
            b'{"query":"changed"}',
        )
        with self.assertRaises(ProviderError):
            c.execute(forged, d)
        self.assertEqual(c.next_id, before)
        c.close(d, suppress=True)

    def test_serial_fixture_and_scope_guard(self):
        _, out = run(
            "serial_probe",
            (
                (proposal("call-1", "a"), proposal("call-2", "b")),
                ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, "done")),
            ),
        )
        self.assertEqual(len(out.execution_order), 2)
        self.assertIn("maxActive=1", str(out.evidence))
        forbidden = ("socket(", "curl ", "system(", "OpenAI", "NVIDIA_API_KEY")
        native = "\n".join(
            Path(ROOT, "src", name).read_text(encoding="utf-8")
            for name in os.listdir(os.path.join(ROOT, "src"))
            if name.endswith((".cpp", ".hpp"))
        )
        self.assertTrue(all(token not in native for token in forbidden))


if __name__ == "__main__":
    unittest.main(verbosity=2)
