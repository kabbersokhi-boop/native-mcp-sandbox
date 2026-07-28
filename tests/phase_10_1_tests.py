#!/usr/bin/env python3
"""Deterministic Phase 10.1 contract, policy, transport, and secrecy tests."""

from __future__ import annotations

from dataclasses import replace
import io
import json
from pathlib import Path
import socket
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.native_mcp_agent.contracts import (  # noqa: E402
    AdvertisedTool, EvidenceProvenance, MessageRole, ProviderMessage, ProviderRequest,
    ProviderToolCallProposal, RequestCorrelationId, ToolCallId, parse_closed_json,
    parse_provider_response,
)
from agent.native_mcp_agent.endpoint_policy import (  # noqa: E402
    validate_fake_loopback_endpoint, validate_production_endpoint,
)
from agent.native_mcp_agent.environment import build_child_environment  # noqa: E402
from agent.native_mcp_agent.errors import FailureClass, ProviderError, http_failure  # noqa: E402
from agent.native_mcp_agent.limits import DEFAULT_LIMITS  # noqa: E402
from agent.native_mcp_agent.redaction import (  # noqa: E402
    REDACTED, redact_exception, redact_headers, redact_json, redact_provider_excerpt, redact_text, redact_url,
)
from agent.native_mcp_agent.retry import decide_retry  # noqa: E402
from agent.native_mcp_agent.transcript import TranscriptEvent, parse_transcript  # noqa: E402
from agent.native_mcp_agent.transport import LoopbackFakeTransport  # noqa: E402
from tests.fake_provider import FakeCase, FakeProviderServer  # noqa: E402


def tool(name: str) -> AdvertisedTool:
    return AdvertisedTool(name, {"type": "object", "additionalProperties": True})


TOOLS = (tool("logs.search"), tool("logs.tail"))


def request(*, message: str = "synthetic", limits=DEFAULT_LIMITS) -> ProviderRequest:
    del limits
    return ProviderRequest(
        "synthetic-model", (ProviderMessage(MessageRole.USER, message),), TOOLS, 128, RequestCorrelationId("req-10-1")
    )


class ContractTests(unittest.TestCase):
    def test_valid_final_one_call_and_multiple_calls(self) -> None:
        final = parse_provider_response(b'{"message":{"role":"assistant","content":"done"}}')
        self.assertEqual(final.message.content, "done")
        one = parse_provider_response(
            b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{}"}]}', advertised_tools=TOOLS
        )
        self.assertEqual(len(one), 1)
        multiple = parse_provider_response(
            b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{}"},{"id":"call-2","name":"logs.tail","arguments":"{}"}]}',
            advertised_tools=TOOLS,
        )
        self.assertEqual([item.name for item in multiple], ["logs.search", "logs.tail"])

    def test_closed_schema_rejections(self) -> None:
        cases = [
            b'{"message":{"role":"assistant"}}',
            b'{"message":{"role":"assistant","content":"x","extra":1}}',
            b'{"message":{"role":"assistant","content":1}}',
            b'{"message":{"role":"assistant","content":"x"},"extra":1}',
            b'{"message":{"role":"assistant","content":"x"},"message":{"role":"assistant","content":"y"}}',
            b'{"toolCalls":[{"id":"","name":"logs.search","arguments":"{}"}]}',
            b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{"}]}',
            b'{"message":{"role":"assistant","content":"x"},"toolCalls":[]}',
            b'{"other":1}',
        ]
        expected = {
            FailureClass.LOCAL_VALIDATION_FAILURE, FailureClass.DUPLICATE_KEY_JSON,
            FailureClass.INVALID_TOOL_PROPOSAL, FailureClass.UNSUPPORTED_PROVIDER_CONTENT,
            FailureClass.MALFORMED_JSON,
        }
        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ProviderError) as raised:
                    parse_provider_response(raw, advertised_tools=TOOLS)
                self.assertIn(raised.exception.failure.classification, expected)
        with self.assertRaises(ProviderError) as raised:
            parse_provider_response(
                b'{"toolCalls":[{"id":"same","name":"logs.search","arguments":"{}"},{"id":"same","name":"logs.search","arguments":"{}"}]}',
                advertised_tools=TOOLS,
            )
        self.assertEqual(raised.exception.failure.classification, FailureClass.REPLAY_OR_DUPLICATE_PROPOSAL)

    def test_duplicate_json_and_limits(self) -> None:
        self.assertEqual(parse_closed_json(b'{"a":1}'), {"a": 1})
        with self.assertRaises(ProviderError) as raised:
            parse_closed_json(b'{"a":1,"a":2}')
        self.assertEqual(raised.exception.failure.classification, FailureClass.DUPLICATE_KEY_JSON)
        exact = replace(DEFAULT_LIMITS, provider_request_bytes=64)
        with self.assertRaises(ProviderError) as raised:
            request(message="x" * 500).to_json_bytes(exact)
        self.assertEqual(raised.exception.failure.classification, FailureClass.REQUEST_TOO_LARGE)
        tiny = replace(DEFAULT_LIMITS, json_nesting_depth=1)
        with self.assertRaises(ProviderError) as raised:
            parse_closed_json(b'{"a":{"b":1}}', tiny)
        self.assertEqual(raised.exception.failure.classification, FailureClass.LOCAL_VALIDATION_FAILURE)

    def test_every_limit_accepts_exact_and_rejects_over_maximum(self) -> None:
        for name, maximum in DEFAULT_LIMITS.HARD_MAX.items():
            with self.subTest(limit=name):
                exact = replace(DEFAULT_LIMITS, **{name: maximum})
                self.assertEqual(exact.as_dict()[name], maximum)
                with self.assertRaises(ProviderError) as raised:
                    replace(DEFAULT_LIMITS, **{name: maximum + 1})
                self.assertEqual(raised.exception.failure.classification, FailureClass.INVALID_PROVIDER_CONFIGURATION)

    def test_action_identity_is_provider_id_independent(self) -> None:
        first = ProviderToolCallProposal(ToolCallId("one"), "logs.search", {"query": "x"})
        second = ProviderToolCallProposal(ToolCallId("two"), "logs.search", {"query": "x"})
        self.assertEqual(first.action_identity, second.action_identity)


class EndpointTests(unittest.TestCase):
    def test_production_endpoint_policy(self) -> None:
        self.assertEqual(validate_production_endpoint("https://provider.example/v1/chat").scheme, "https")
        for url in (
            "http://provider.example/v1", "https://user:pass@provider.example/v1", "https://provider.example/v1#x",
            "https:///v1", "ftp://provider.example/v1", "https://provider.example:bad/v1",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ProviderError):
                    validate_production_endpoint(url)
        with self.assertRaises(ProviderError) as raised:
            validate_production_endpoint("https://provider.example/v1", verify_tls=False)
        self.assertEqual(raised.exception.failure.classification, FailureClass.TLS_VERIFICATION_FAILURE)

    def test_fake_endpoint_is_explicit_and_loopback_only(self) -> None:
        def loopback(_host, _port, _family, _type):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 1))]

        self.assertTrue(validate_fake_loopback_endpoint("http://localhost:1234/x", allow_loopback_http=True, resolver=loopback).loopback_only)
        for host in ("0.0.0.0", "public.example"):
            with self.subTest(host=host):
                with self.assertRaises(ProviderError):
                    validate_fake_loopback_endpoint(f"http://{host}:1234/x", allow_loopback_http=True, resolver=loopback)
        def mixed(_host, _port, _family, _type):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 1)), (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 1))]
        with self.assertRaises(ProviderError):
            validate_fake_loopback_endpoint("http://localhost:1234/x", allow_loopback_http=True, resolver=mixed)
        with self.assertRaises(ProviderError):
            validate_fake_loopback_endpoint("http://localhost:1234/x", allow_loopback_http=False, resolver=loopback)


class TransportTests(unittest.TestCase):
    def transport(self, limits=DEFAULT_LIMITS):
        return LoopbackFakeTransport(sleep=lambda _seconds: None)

    def run_case(self, case: FakeCase, limits=DEFAULT_LIMITS):
        with FakeProviderServer(case) as provider:
            return self.transport(limits).send(provider.validated_endpoint(), request(), limits=limits, correlation_id="req-10-1")

    def test_successful_bounded_requests(self) -> None:
        result = self.run_case(FakeCase.FINAL)
        self.assertEqual(result.message.content, "synthetic guidance")
        result = self.run_case(FakeCase.ONE_CALL)
        self.assertEqual(result[0].call_id, "call-1")
        result = self.run_case(FakeCase.MULTIPLE_CALLS)
        self.assertEqual(len(result), 2)

    def test_response_failures_and_statuses(self) -> None:
        cases = {
            FakeCase.MALFORMED_JSON: FailureClass.MALFORMED_JSON,
            FakeCase.DUPLICATE_KEYS: FailureClass.DUPLICATE_KEY_JSON,
            FakeCase.TRUNCATED: FailureClass.TRUNCATED_RESPONSE,
            FakeCase.INVALID_CONTENT_TYPE: FailureClass.INVALID_CONTENT_TYPE,
            FakeCase.MISSING_CONTENT_TYPE: FailureClass.INVALID_CONTENT_TYPE,
            FakeCase.REDIRECT: FailureClass.REDIRECT_REJECTED,
            FakeCase.UNEXPECTED_FIELDS: FailureClass.LOCAL_VALIDATION_FAILURE,
            FakeCase.MIXED: FailureClass.LOCAL_VALIDATION_FAILURE,
            FakeCase.DUPLICATE_CALL_IDS: FailureClass.REPLAY_OR_DUPLICATE_PROPOSAL,
            FakeCase.MALFORMED_ARGUMENTS: FailureClass.MALFORMED_JSON,
            FakeCase.EXCESSIVE_PROPOSALS: FailureClass.INVALID_TOOL_PROPOSAL,
        }
        one_attempt = replace(DEFAULT_LIMITS, provider_attempt_count=1)
        for case, classification in cases.items():
            with self.subTest(case=case):
                with self.assertRaises(ProviderError) as raised:
                    self.run_case(case, one_attempt)
                self.assertEqual(raised.exception.failure.classification, classification)
        for status in (400, 401, 403, 404, 408, 413, 422, 429, 500, 502, 503, 504):
            self.assertEqual(http_failure(status).status_code, status)

    def test_size_timeout_connection_and_retry(self) -> None:
        tiny = replace(DEFAULT_LIMITS, provider_response_bytes=128, provider_attempt_count=1)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.OVERSIZED, tiny)
        self.assertEqual(raised.exception.failure.classification, FailureClass.OVERSIZED_RESPONSE)
        timed = replace(DEFAULT_LIMITS, provider_read_inactivity_timeout_ms=20, provider_total_timeout_ms=100, provider_attempt_count=1)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.READ_TIMEOUT, timed)
        self.assertIn(raised.exception.failure.classification, {FailureClass.READ_TIMEOUT, FailureClass.TOTAL_REQUEST_TIMEOUT})
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.CONNECTION_CLOSE, replace(DEFAULT_LIMITS, provider_attempt_count=1))
        self.assertIn(raised.exception.failure.classification, {FailureClass.DNS_OR_CONNECTION_FAILURE, FailureClass.TRUNCATED_RESPONSE})
        decision = decide_retry(http_failure(429, retry_after_ms=500), completed_attempts=1, remaining_ms=600, limits=DEFAULT_LIMITS)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.delay_ms, 500)
        self.assertFalse(decide_retry(http_failure(401), completed_attempts=1, remaining_ms=600, limits=DEFAULT_LIMITS).eligible)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.STATUS_503, replace(DEFAULT_LIMITS, provider_attempt_count=2))
        self.assertEqual(raised.exception.failure.classification, FailureClass.RETRY_EXHAUSTED)


class RedactionEnvironmentTranscriptTests(unittest.TestCase):
    def test_redaction_is_deterministic_idempotent_and_structural(self) -> None:
        secrets = ("api-sentinel-10-1", "bearer-sentinel-10-1", "proxy-sentinel-10-1", "exception-sentinel-10-1")
        source = "Authorization: Bearer api-sentinel-10-1, bearer-sentinel-10-1; proxy-sentinel-10-1."
        once = redact_text(source, secrets)
        self.assertNotIn("sentinel-10-1", once)
        self.assertEqual(once, redact_text(once, secrets))
        self.assertEqual(redact_headers({"Authorization": "Bearer api-sentinel-10-1", "X-Id": "ok"}, secrets)["authorization"], REDACTED)
        self.assertNotIn("api-sentinel-10-1", json.dumps(redact_json({"api_key": secrets[0], "message": source}, secrets)))
        self.assertNotIn("user:pass", redact_url("https://user:pass@provider.example/x"))
        self.assertNotIn(secrets[-1], redact_exception(RuntimeError(secrets[-1]), secrets))
        self.assertNotIn(secrets[0], redact_provider_excerpt(secrets[0], secrets))
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            print(redact_exception(RuntimeError(secrets[-1]), secrets))
            print(redact_provider_excerpt(secrets[0], secrets), file=sys.stderr)
        self.assertNotIn("sentinel-10-1", stdout.getvalue())
        self.assertNotIn("sentinel-10-1", stderr.getvalue())

    def test_environment_is_new_minimal_mapping(self) -> None:
        parent = {"LANG": "C.UTF-8", "PATH": "/usr/bin", "OPENAI_API_KEY": "api-sentinel-10-1", "HTTPS_PROXY": "proxy-sentinel-10-1"}
        result = build_child_environment(parent, ("LANG", "PATH"))
        self.assertEqual(result, {"LANG": "C.UTF-8", "PATH": "/usr/bin"})
        for name in ("OPENAI_API_KEY", "HTTPS_PROXY"):
            with self.assertRaises(ProviderError):
                build_child_environment(parent, (name,))
        with self.assertRaises(ProviderError):
            build_child_environment(parent, ("bad-name",))
        with self.assertRaises(ProviderError):
            build_child_environment({"LANG": "x" * 20}, ("LANG",), max_value_bytes=4)

    def test_transcript_canonical_and_closed(self) -> None:
        event = TranscriptEvent("provider_response", "fake-loopback", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.PROVIDER_SUGGESTION, metadata={"authorization": "api-sentinel-10-1", "mode": "synthetic-only"})
        first = event.to_json_bytes()
        second = event.to_json_bytes()
        self.assertEqual(first, second)
        self.assertNotIn(b"api-sentinel-10-1", first)
        self.assertEqual(parse_transcript(first).to_json_bytes(), first)
        with self.assertRaises(ProviderError):
            parse_transcript(first[:-1] + b',"extra":1}')

    def test_representative_scenarios_are_byte_identical_twice(self) -> None:
        outputs = []
        for _ in range(2):
            event = TranscriptEvent("failure", "fake-loopback", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, failure_class=FailureClass.HTTP_401_AUTHENTICATION_FAILURE, retry_eligible=False, byte_count=17)
            outputs.append(event.to_json_bytes())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
