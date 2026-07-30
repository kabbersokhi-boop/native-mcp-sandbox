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
    ValidatedEndpoint, validate_fake_loopback_endpoint, validate_production_endpoint,
)
from agent.native_mcp_agent.environment import build_child_environment  # noqa: E402
from agent.native_mcp_agent.errors import FailureClass, ProviderError, http_failure  # noqa: E402
from agent.native_mcp_agent.limits import DEFAULT_LIMITS, HARD_LIMITS  # noqa: E402
from agent.native_mcp_agent.redaction import (  # noqa: E402
    REDACTED, redact_exception, redact_headers, redact_json, redact_provider_excerpt, redact_text, redact_url,
)
from agent.native_mcp_agent.retry import decide_retry  # noqa: E402
from agent.native_mcp_agent.transcript import TranscriptEvent, parse_transcript  # noqa: E402
from agent.native_mcp_agent.transport import LoopbackFakeTransport  # noqa: E402
from tests.fake_provider import FakeCase, FakeProviderServer  # noqa: E402


def tool(name: str) -> AdvertisedTool:
    properties = {}
    if name == "logs.search":
        properties = {"query": {"type": "string", "minLength": 1, "maxLength": 256}}
    elif name == "logs.tail":
        properties = {"lines": {"type": "integer", "minimum": 1, "maximum": 128}}
    return AdvertisedTool(name, {"type": "object", "properties": properties, "required": [], "additionalProperties": False})


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

    def test_closed_tool_schema_subset(self) -> None:
        nested = {
            "type": "object", "additionalProperties": False,
            "properties": {"options": {"type": "object", "additionalProperties": False,
                                         "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}},
                                         "required": ["mode"]},
                           "values": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 8}}},
            "required": ["options"],
        }
        nested_tool = AdvertisedTool("nested", nested)
        valid = b'{"toolCalls":[{"id":"call-1","name":"nested","arguments":"{\\"options\\":{\\"mode\\":\\"safe\\"},\\"values\\":[1,2]}"}]}'
        self.assertEqual(parse_provider_response(valid, advertised_tools=(nested_tool,))[0].name, "nested")
        for arguments in (
            '{"options":{"mode":"safe","extra":1}}',
            '{"options":{}}',
            '{"values":[1,"bad"]}',
            '{"values":[1,2,3,4,5,6,7,8,9]}',
            '{"options":{"mode":"other"}}',
        ):
            raw = json.dumps({"toolCalls": [{"id": "call-1", "name": "nested", "arguments": arguments}]}).encode()
            with self.assertRaises(ProviderError):
                parse_provider_response(raw, advertised_tools=(nested_tool,))
        bad_schemas = (
            {"type": "object", "properties": [], "additionalProperties": False},
            {"type": "object", "properties": {"x": {"type": "wat"}}, "additionalProperties": False},
            {"type": "object", "properties": {"x": {"type": "string", "unknown": 1}}, "additionalProperties": False},
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["missing"], "additionalProperties": False},
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x", "x"], "additionalProperties": False},
            {"type": "object", "properties": {}, "additionalProperties": True},
        )
        for schema in bad_schemas:
            with self.subTest(schema=schema):
                with self.assertRaises(ProviderError):
                    AdvertisedTool("bad", schema)

    def test_configured_limits_are_operational(self) -> None:
        message = ProviderMessage(MessageRole.USER, "x" * 10)
        small = replace(DEFAULT_LIMITS, message_bytes=10, provider_request_bytes=8_192)
        req = ProviderRequest("m", (message,), TOOLS, 128, RequestCorrelationId("req-10-1"))
        self.assertLessEqual(len(req.to_json_bytes(small)), small.provider_request_bytes)
        with self.assertRaises(ProviderError):
            req.to_json_bytes(replace(small, message_bytes=9))
        self.assertEqual(len(parse_closed_json(b'{"x":1}', replace(DEFAULT_LIMITS, provider_response_bytes=7))), 1)
        with self.assertRaises(ProviderError):
            parse_closed_json(b'{"x":1}', replace(DEFAULT_LIMITS, provider_response_bytes=6))
        self.assertEqual(parse_closed_json(b'{"a":1}', replace(DEFAULT_LIMITS, object_array_items=1)), {"a": 1})
        with self.assertRaises(ProviderError):
            parse_closed_json(b'{"a":1,"b":2}', replace(DEFAULT_LIMITS, object_array_items=1))
        self.assertEqual(parse_closed_json(b'{"a":{"b":1}}', replace(DEFAULT_LIMITS, json_nesting_depth=2)), {"a": {"b": 1}})
        with self.assertRaises(ProviderError):
            parse_closed_json(b'{"a":{"b":1}}', replace(DEFAULT_LIMITS, json_nesting_depth=1))

    def test_configured_collection_and_serialization_boundaries(self) -> None:
        messages = tuple(ProviderMessage(MessageRole.USER, "x") for _ in range(9))
        request_with_messages = ProviderRequest("m", messages, TOOLS, 128, RequestCorrelationId("req-10-1"))
        with self.assertRaises(ProviderError):
            request_with_messages.to_json_bytes(DEFAULT_LIMITS)
        self.assertTrue(request_with_messages.to_json_bytes(replace(DEFAULT_LIMITS, message_count=9, provider_request_bytes=8192)))
        tools = tuple(tool(f"tool-{index}") for index in range(9))
        request_with_tools = ProviderRequest("m", (ProviderMessage(MessageRole.USER, "x"),), tools, 128, RequestCorrelationId("req-10-1"))
        with self.assertRaises(ProviderError):
            request_with_tools.to_json_bytes(DEFAULT_LIMITS)
        self.assertTrue(request_with_tools.to_json_bytes(replace(DEFAULT_LIMITS, advertised_tool_count=9, provider_request_bytes=8192)))
        encoded_request = request().to_json_bytes()
        self.assertEqual(request().to_json_bytes(replace(DEFAULT_LIMITS, provider_request_bytes=len(encoded_request))), encoded_request)
        with self.assertRaises(ProviderError) as raised:
            request().to_json_bytes(replace(DEFAULT_LIMITS, provider_request_bytes=len(encoded_request) - 1))
        self.assertEqual(raised.exception.failure.classification, FailureClass.REQUEST_TOO_LARGE)
        described = AdvertisedTool("described", {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, "x" * 100)
        described_request = ProviderRequest("m", (ProviderMessage(MessageRole.USER, "x"),), (described,), 128, RequestCorrelationId("req-10-1"))
        definition = json.dumps({"name": described.name, "description": described.description, "parameters": described.parameters}, sort_keys=True, separators=(",", ":")).encode()
        self.assertTrue(described_request.to_json_bytes(replace(DEFAULT_LIMITS, tool_definition_bytes=len(definition), provider_request_bytes=8192)))
        with self.assertRaises(ProviderError):
            described_request.to_json_bytes(replace(DEFAULT_LIMITS, tool_definition_bytes=len(definition) - 1, provider_request_bytes=8192))
        calls = [{"id": f"call-{index}", "name": "logs.search", "arguments": "{}"} for index in range(5)]
        raw = json.dumps({"toolCalls": calls}).encode()
        with self.assertRaises(ProviderError):
            parse_provider_response(raw, advertised_tools=TOOLS)
        self.assertEqual(len(parse_provider_response(raw, advertised_tools=TOOLS, limits=replace(DEFAULT_LIMITS, proposed_tool_call_count=5))), 5)
        large_args = json.dumps({"query": "x" * 100})
        large_raw = json.dumps({"toolCalls": [{"id": "call-1", "name": "logs.search", "arguments": large_args}]}).encode()
        argument_size = len(large_args.encode())
        self.assertEqual(len(parse_provider_response(large_raw, advertised_tools=TOOLS, limits=replace(DEFAULT_LIMITS, tool_argument_bytes=argument_size))), 1)
        with self.assertRaises(ProviderError):
            parse_provider_response(large_raw, advertised_tools=TOOLS, limits=replace(DEFAULT_LIMITS, tool_argument_bytes=argument_size - 1))
        transcript = TranscriptEvent("event", "adapter", "model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, metadata={"mode": "synthetic"})
        transcript_bytes = transcript.to_json_bytes()
        self.assertEqual(parse_transcript(transcript_bytes, replace(DEFAULT_LIMITS, transcript_bytes=len(transcript_bytes))).event, "event")
        with self.assertRaises(ProviderError):
            parse_transcript(transcript_bytes, replace(DEFAULT_LIMITS, transcript_bytes=len(transcript_bytes) - 1))
        self.assertTrue(decide_retry(http_failure(503), completed_attempts=1, remaining_ms=500, limits=replace(DEFAULT_LIMITS, retry_backoff_ms=100)).eligible)
        self.assertEqual(decide_retry(http_failure(503), completed_attempts=1, remaining_ms=500, limits=replace(DEFAULT_LIMITS, retry_backoff_ms=100)).delay_ms, 100)

    def test_provider_parsers_are_project_owned_for_malformed_inputs(self) -> None:
        malformed = [None, bytearray(b"{}"), b"\xff", b"[", b'{"x": NaN}', b'{"x":1,"x":2}']
        for raw in malformed:
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(ProviderError) as raised:
                    parse_closed_json(raw)  # type: ignore[arg-type]
                self.assertIsInstance(raised.exception.failure.classification, FailureClass)


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

    def test_transport_revalidates_forged_authority_before_connection(self) -> None:
        attempts = []
        def factory(host, port, timeout):
            attempts.append((host, port, timeout))
            raise AssertionError("connection factory must not be called")
        transport = LoopbackFakeTransport(connection_factory=factory)
        forged = [
            "8.8.8.8", "10.0.0.1", "169.254.1.1", "0.0.0.0", "::", "ff02::1", "localhost",
        ]
        for host in forged:
            endpoint = ValidatedEndpoint(f"http://127.0.0.1:1234/x", "http", "127.0.0.1", host, 1234, "/x", True)
            with self.subTest(host=host), self.assertRaises(ProviderError):
                transport.send(endpoint, request(), correlation_id="req-10-1")
        for endpoint in (
            ValidatedEndpoint("http://127.0.0.1:0/x", "http", "127.0.0.1", "127.0.0.1", 0, "/x", True),
            ValidatedEndpoint("http://127.0.0.1:1234/x", "http", "127.0.0.1", "127.0.0.1", 1234, "x", True),
            ValidatedEndpoint("https://127.0.0.1:1234/x", "https", "127.0.0.1", "127.0.0.1", 1234, "/x", True),
            ValidatedEndpoint("http://127.0.0.1:1234/x", "http", "127.0.0.1", "127.0.0.2", 1234, "/x", True),
            ValidatedEndpoint("http://127.0.0.1:1234/x?secret=1", "http", "127.0.0.1", "127.0.0.1", 1234, "/x", True),
        ):
            with self.assertRaises(ProviderError):
                transport.send(endpoint, request(), correlation_id="req-10-1")
        self.assertEqual(attempts, [])


class TransportTests(unittest.TestCase):
    def transport(self, limits=DEFAULT_LIMITS):
        return LoopbackFakeTransport(sleep=lambda _seconds: None)

    def run_case(self, case: FakeCase, limits=DEFAULT_LIMITS):
        with FakeProviderServer(case) as provider:
            return self.transport(limits).send(provider.validated_endpoint(), request(), limits=limits, correlation_id="req-10-1")

    def test_successful_bounded_requests(self) -> None:
        with FakeProviderServer(FakeCase.FINAL) as provider:
            result = self.transport().send(provider.validated_endpoint(), request(), correlation_id="req-10-1")
            self.assertEqual(result.message.content, "synthetic guidance")
            self.assertTrue(provider.request_headers)
            self.assertNotIn("authorization", provider.request_headers[0])
            self.assertNotIn("proxy-authorization", provider.request_headers[0])
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
            case = FakeCase[f"STATUS_{status}"]
            with self.subTest(status=status), self.assertRaises(ProviderError) as raised:
                self.run_case(case, one_attempt)
            self.assertEqual(raised.exception.failure.status_code, status)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.STATUS_409, one_attempt)
        self.assertEqual(raised.exception.failure.classification, FailureClass.OTHER_PERMANENT_4XX)
        for case in (FakeCase.REDIRECT_301, FakeCase.REDIRECT_302, FakeCase.REDIRECT_303, FakeCase.REDIRECT_307, FakeCase.REDIRECT_308):
            with self.subTest(case=case), self.assertRaises(ProviderError) as raised:
                self.run_case(case, one_attempt)
            self.assertEqual(raised.exception.failure.classification, FailureClass.REDIRECT_REJECTED)
            self.assertNotIn("provider.invalid", str(raised.exception))
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.RETRY_AFTER, replace(DEFAULT_LIMITS, provider_attempt_count=1))
        self.assertEqual(raised.exception.failure.classification, FailureClass.HTTP_429_RATE_LIMITED)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.EXCESSIVE_RETRY_AFTER, replace(DEFAULT_LIMITS, provider_attempt_count=1))
        self.assertEqual(raised.exception.failure.classification, FailureClass.HTTP_429_RATE_LIMITED)

    def test_size_timeout_connection_and_retry(self) -> None:
        tiny = replace(DEFAULT_LIMITS, provider_response_bytes=128, provider_attempt_count=1)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.OVERSIZED, tiny)
        self.assertEqual(raised.exception.failure.classification, FailureClass.OVERSIZED_RESPONSE)
        timed = replace(DEFAULT_LIMITS, provider_read_inactivity_timeout_ms=20, provider_total_timeout_ms=100, provider_attempt_count=1)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.READ_TIMEOUT, timed)
        self.assertEqual(raised.exception.failure.classification, FailureClass.READ_TIMEOUT)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.CONNECTION_CLOSE, replace(DEFAULT_LIMITS, provider_attempt_count=1))
        self.assertEqual(raised.exception.failure.classification, FailureClass.DNS_OR_CONNECTION_FAILURE)
        decision = decide_retry(http_failure(429, retry_after_ms=500), completed_attempts=1, remaining_ms=600, limits=DEFAULT_LIMITS)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.delay_ms, 500)
        self.assertFalse(decide_retry(http_failure(401), completed_attempts=1, remaining_ms=600, limits=DEFAULT_LIMITS).eligible)
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.STATUS_503, replace(DEFAULT_LIMITS, provider_attempt_count=2))
        self.assertEqual(raised.exception.failure.classification, FailureClass.RETRY_EXHAUSTED)
        self.assertEqual(self.run_case(FakeCase.RETRY_SUCCESS, replace(DEFAULT_LIMITS, provider_attempt_count=2)).message.content, "synthetic guidance")
        self.assertEqual(
            self.run_case(FakeCase.DELAYED, replace(DEFAULT_LIMITS, provider_read_inactivity_timeout_ms=500, provider_total_timeout_ms=1_000, provider_attempt_count=1)).message.content,
            "synthetic guidance",
        )
        with self.assertRaises(ProviderError) as raised:
            self.run_case(FakeCase.DELAYED, replace(DEFAULT_LIMITS, provider_read_inactivity_timeout_ms=1_000, provider_total_timeout_ms=50, provider_attempt_count=1))
        self.assertEqual(raised.exception.failure.classification, FailureClass.TOTAL_REQUEST_TIMEOUT)

    def test_request_too_large_is_rejected_before_transmission(self) -> None:
        limits = replace(DEFAULT_LIMITS, provider_request_bytes=64)
        with FakeProviderServer(FakeCase.FINAL) as provider:
            with self.assertRaises(ProviderError) as raised:
                self.transport(limits).send(provider.validated_endpoint(), request(message="x" * 200), limits=limits, correlation_id="req-10-1")
            self.assertEqual(raised.exception.failure.classification, FailureClass.REQUEST_TOO_LARGE)
            self.assertEqual(provider.request_count, 0)

    def test_malformed_declared_lengths_are_classified(self) -> None:
        for case, expected in (
            (FakeCase.MALFORMED_LENGTH, FailureClass.TRUNCATED_RESPONSE),
            (FakeCase.NEGATIVE_LENGTH, FailureClass.TRUNCATED_RESPONSE),
            (FakeCase.OVERSIZED_DECLARED_LENGTH, FailureClass.OVERSIZED_RESPONSE),
        ):
            with self.subTest(case=case), self.assertRaises(ProviderError) as raised:
                self.run_case(case, replace(DEFAULT_LIMITS, provider_attempt_count=1))
            self.assertEqual(raised.exception.failure.classification, expected)


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

    def test_redaction_is_safe_at_utf8_and_overlap_boundaries(self) -> None:
        secret = "SECRET-BOUNDARY-1234"
        for source in (
            "x" * (len(secret) - 1) + secret,
            "x" * len(secret) + secret,
            "x" * (len(secret) + 1) + secret,
            secret + "," + secret,
            "abcdeFGHIJ",  # used with overlapping sentinels below
            "é" * 8 + secret,
        ):
            result = redact_text(source, (secret,), maximum=len(secret) + 3)
            self.assertLessEqual(len(result.encode("utf-8")), len(secret) + 3)
            self.assertNotIn(secret, result)
            self.assertEqual(result, redact_text(result, (secret,), maximum=len(secret) + 3))
        overlap = redact_text("abcdeFGHIJ", ("abcdeFG", "deFGHIJ"), maximum=32)
        self.assertNotIn("abcde", overlap)
        self.assertNotIn("deFG", overlap)
        self.assertEqual(redact_json({"path": "/absolute/secret", "diagnostic": "pid=424242", "count": 42}), {"path": REDACTED, "diagnostic": REDACTED, "count": 42})

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
        for kwargs in (
            {"parent": {"LANG": "bad\x00value"}, "allowlist": ("LANG",)},
            {"parent": {"LANG": "ok"}, "allowlist": ("LANG",), "required": {"LANG": "bad\x00value"}},
            {"parent": {"LANG": "ok"}, "allowlist": ("bad-name",)},
            {"parent": {"LANG": "ok"}, "allowlist": ("LANG", "LANG")},
            {"parent": {"LANG": "x" * 20}, "allowlist": ("LANG",), "max_value_bytes": 4},
            {"parent": {"HTTP_PROXY": "http://proxy"}, "allowlist": ("HTTP_PROXY",)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProviderError):
                build_child_environment(**kwargs)
        self.assertEqual(
            build_child_environment({"HTTP_PROXY": "http://127.0.0.1:1"}, ("HTTP_PROXY",), allow_proxy=True, provider_child=False),
            {"HTTP_PROXY": "http://127.0.0.1:1"},
        )
        with self.assertRaises(ProviderError):
            build_child_environment({"HTTP_PROXY": "http://127.0.0.1:1"}, ("HTTP_PROXY",), allow_proxy=True)

    def test_transcript_canonical_and_closed(self) -> None:
        event = TranscriptEvent("provider_response", "fake-loopback", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.PROVIDER_SUGGESTION, metadata={"mode": "synthetic-only"})
        first = event.to_json_bytes()
        second = event.to_json_bytes()
        self.assertEqual(first, second)
        self.assertNotIn(b"api-sentinel-10-1", first)
        self.assertEqual(parse_transcript(first).to_json_bytes(), first)
        with self.assertRaises(ProviderError):
            parse_transcript(first[:-1] + b',"extra":1}')

    def test_transcript_parser_bounds_types_and_failures(self) -> None:
        event = TranscriptEvent("failure", "fake-loopback", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, metadata={"mode": "synthetic"})
        raw = event.to_json_bytes()
        exact = replace(DEFAULT_LIMITS, transcript_bytes=len(raw))
        self.assertEqual(parse_transcript(raw, exact).event, "failure")
        with self.assertRaises(ProviderError) as raised:
            parse_transcript(b" " + raw, exact)
        self.assertEqual(raised.exception.failure.classification, FailureClass.OVERSIZED_RESPONSE)
        base = json.loads(raw)
        bad_values = [
            {**base, "metadata": []}, {**base, "metadata": {"mode": 1}},
            {**base, "retryEligible": 1}, {**base, "byteCount": True}, {**base, "byteCount": -1},
            {**base, "failureClass": "not-a-failure"}, {**base, "provenance": "not-provenance"},
            {**base, "proposalIds": ["call-1", "call-1"]}, {**base, "proposalIds": ["call/1"]},
            {**base, "event": "Authorization: Bearer secret"}, {**base, "adapter": "/absolute/path"},
            {**base, "model": "api-key-sentinel"}, {**base, "correlationId": "user:pass@host"},
        ]
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(ProviderError) as raised:
                    parse_transcript(json.dumps(value).encode())
                self.assertNotIn("secret", str(raised.exception).lower())
                self.assertNotIn("api-key-sentinel", repr(raised.exception))
        deep = {**base, "metadata": {"mode": "x"}}
        for _ in range(DEFAULT_LIMITS.json_nesting_depth + 2):
            deep = {"x": deep}
        with self.assertRaises(ProviderError):
            parse_transcript(json.dumps(deep).encode())
        too_many = {**base, "metadata": {key: "x" for key in ["mode", "phase", "source", "reason", "status", "retry", "category", "provider", "operation"]}}
        with self.assertRaises(ProviderError):
            parse_transcript(json.dumps(too_many).encode(), replace(DEFAULT_LIMITS, object_array_items=2))

    def test_transcript_identity_fields_never_emit_sentinels(self) -> None:
        sentinels = (
            "sk-api-sentinel", "Bearer-token-sentinel", "Authorization-header-sentinel",
            "proxy-user:proxy-pass", "/home/secret/file", "pid=424242", "user:pass@host",
        )
        for sentinel in sentinels:
            with self.subTest(sentinel=sentinel):
                with self.assertRaises(ProviderError) as raised:
                    TranscriptEvent(sentinel, "fake-loopback", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.PROVIDER_SUGGESTION)
                self.assertNotIn(sentinel, str(raised.exception))
                self.assertNotIn(sentinel, repr(raised.exception))
                self.assertNotIn(sentinel, json.dumps(raised.exception.failure.__dict__, default=str))

    def test_representative_scenarios_are_byte_identical_twice(self) -> None:
        outputs = []
        for _ in range(2):
            event = TranscriptEvent("failure", "fake-loopback", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, failure_class=FailureClass.HTTP_401_AUTHENTICATION_FAILURE, retry_eligible=False, byte_count=17)
            outputs.append(event.to_json_bytes())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
