#!/usr/bin/env python3
"""Offline deterministic tests for the Phase 10.4 OpenAI-compatible adapter."""

from __future__ import annotations

from dataclasses import replace
import json
import os
import ssl
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.native_mcp_agent.contracts import (  # noqa: E402
    AdvertisedTool, MessageRole, ProviderMessage, ProviderRequest, RequestCorrelationId,
)
from agent.native_mcp_agent.endpoint_policy import ValidatedEndpoint  # noqa: E402
from agent.native_mcp_agent.errors import FailureClass, ProviderError, failure  # noqa: E402
from agent.native_mcp_agent.limits import DEFAULT_LIMITS  # noqa: E402
from agent.native_mcp_agent.mcp_orchestrator import BoundedProvider, Orchestrator, McpStdioClient, ScriptedProvider  # noqa: E402
from agent.native_mcp_agent.openai_compatible import (  # noqa: E402
    OpenAICompatibleConfig, OpenAICompatibleProvider, OpenAICompatibleTransport, SyntheticFixture,
    openai_request_bytes, parse_openai_compatible_response,
    synthetic_fixture_message,
)
from fake_provider import FakeCase, FakeProviderServer  # noqa: E402
from scripts.phase_10_4_openai_smoke import build_synthetic_smoke_request  # noqa: E402


TOOLS = (
    AdvertisedTool("logs.search", {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 32}}, "required": ["query"], "additionalProperties": False}, "search"),
    AdvertisedTool("logs.tail", {"type": "object", "properties": {"lines": {"type": "integer", "minimum": 1, "maximum": 9}}, "required": ["lines"], "additionalProperties": False}, "tail"),
)
SENTINEL = "PHASE10_4_CREDENTIAL_SENTINEL_NOT_LEAKED"


def request() -> ProviderRequest:
    return ProviderRequest("synthetic-model", (synthetic_fixture_message(SyntheticFixture.PHASE_10_4_TEST_PROMPT),), TOOLS, 32, RequestCorrelationId("req-10-4"))


def config(endpoint: str, **changes: object) -> OpenAICompatibleConfig:
    values: dict[str, object] = {"endpoint": endpoint, "model": "synthetic-model", "credential_env": "NATIVE_MCP_PHASE10_4_TOKEN", "allow_loopback_http": True}
    values.update(changes)
    return OpenAICompatibleConfig(**values)  # type: ignore[arg-type]


class ConfigAndMappingTests(unittest.TestCase):
    def test_closed_config_and_no_eager_credential_load(self) -> None:
        os.environ["NATIVE_MCP_PHASE10_4_TOKEN"] = SENTINEL
        cfg = OpenAICompatibleConfig.from_mapping({"endpoint": "https://provider.example/v1/chat/completions", "model": "operator/model", "credentialEnv": "NATIVE_MCP_PHASE10_4_TOKEN", "limits": {"provider_attempt_count": 2}})
        provider = OpenAICompatibleProvider(cfg)
        self.assertEqual(str(cfg.model), "operator/model")
        self.assertNotIn(SENTINEL, repr(provider))
        for raw in (
            {"endpoint": "https://x", "model": "m", "credentialEnv": "NATIVE_MCP_X", "extra": True},
            {"endpoint": "https://x", "model": "m", "credentialEnv": "BAD"},
            {"endpoint": "https://x", "model": "m", "credentialEnv": "NATIVE_MCP_X", "verifyTls": False},
            {"endpoint": "https://x", "model": "m", "credentialEnv": "NATIVE_MCP_X", "limits": {"unknown": 1}},
        ):
            with self.subTest(raw=raw), self.assertRaises(ProviderError):
                OpenAICompatibleConfig.from_mapping(raw)

    def test_request_schema_model_tools_stream_and_exact_byte_limit(self) -> None:
        cfg = config("http://127.0.0.1:1/v1/chat/completions")
        raw = openai_request_bytes(request(), cfg)
        value = json.loads(raw)
        self.assertEqual(set(value), {"model", "messages", "tools", "tool_choice", "max_tokens", "stream"})
        self.assertEqual(value["model"], "synthetic-model")
        self.assertFalse(value["stream"])
        self.assertEqual(value["tools"], [
            {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": json.loads(json.dumps(tool.parameters))}}
            for tool in TOOLS
        ])
        exact = replace(cfg, limits=replace(DEFAULT_LIMITS, provider_request_bytes=len(raw)))
        self.assertEqual(openai_request_bytes(request(), exact), raw)
        with self.assertRaises(ProviderError) as raised:
            openai_request_bytes(request(), replace(cfg, limits=replace(DEFAULT_LIMITS, provider_request_bytes=len(raw) - 1)))
        self.assertEqual(raised.exception.failure.classification, FailureClass.REQUEST_TOO_LARGE)
        with self.assertRaises(ProviderError):
            openai_request_bytes(ProviderRequest("different", request().messages, TOOLS, 32, RequestCorrelationId("req-10-4-1")), cfg)

    def test_synthetic_only_rejects_unmarked_content_and_closed_fixture_rejects_arbitrary_strings(self) -> None:
        cfg = config("http://127.0.0.1:1/v1/chat/completions")
        unmarked = ProviderRequest("synthetic-model", (ProviderMessage(MessageRole.USER, "arbitrary host evidence"),), TOOLS, 32, RequestCorrelationId("req-10-4"))
        with self.assertRaises(ProviderError) as raised:
            openai_request_bytes(unmarked, cfg)
        self.assertEqual(raised.exception.failure.classification, FailureClass.LOCAL_AUTHORIZATION_FAILURE)
        for forged_fixture in ("arbitrary host evidence", (MessageRole.USER, "arbitrary host evidence")):
            with self.subTest(forged_fixture=forged_fixture), self.assertRaises(ProviderError) as raised:
                synthetic_fixture_message(forged_fixture)  # type: ignore[arg-type]
            self.assertEqual(raised.exception.failure.classification, FailureClass.LOCAL_AUTHORIZATION_FAILURE)

    def test_authorized_synthetic_content_succeeds_with_deterministic_serialization(self) -> None:
        cfg = config("http://127.0.0.1:1/v1/chat/completions")
        first = request()
        second = request()
        self.assertEqual(openai_request_bytes(first, cfg), openai_request_bytes(second, cfg))
        self.assertEqual(json.loads(openai_request_bytes(first, cfg))["messages"], [{"role": "user", "content": "synthetic-only prompt"}])

    def test_manual_synthetic_smoke_uses_authorized_egress_path(self) -> None:
        cfg = config("http://127.0.0.1:1/v1/chat/completions")
        smoke_request = build_synthetic_smoke_request(cfg)
        self.assertIn(b"Return a short synthetic acknowledgement.", openai_request_bytes(smoke_request, cfg))

    def test_endpoint_policy_rejects_http_production_userinfo_fragment_and_disabled_tls(self) -> None:
        for endpoint, kwargs, kind in (
            ("http://example.test/v1", {"allow_loopback_http": False}, FailureClass.INSECURE_SCHEME),
            ("https://user@example.test/v1", {"allow_loopback_http": False}, FailureClass.ENDPOINT_POLICY_REJECTION),
            ("https://example.test/v1#x", {"allow_loopback_http": False}, FailureClass.ENDPOINT_POLICY_REJECTION),
            ("https://example.test/v1", {"verify_tls": False, "allow_loopback_http": False}, FailureClass.TLS_VERIFICATION_FAILURE),
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ProviderError) as raised:
                    config(endpoint, **kwargs).validated_endpoint()
                self.assertEqual(raised.exception.failure.classification, kind)


class ResponseParsingTests(unittest.TestCase):
    def parse(self, value: bytes):
        return parse_openai_compatible_response(value, advertised_tools=TOOLS)

    def test_final_one_and_multiple_calls(self) -> None:
        self.assertEqual(self.parse(b'{"choices":[{"message":{"role":"assistant","content":"done"}}]}').message.content, "done")
        one = self.parse(b'{"choices":[{"message":{"role":"assistant","tool_calls":[{"id":"call-1","type":"function","function":{"name":"logs.search","arguments":"{\\"query\\":\\"x\\"}"}}]}}]}')
        multiple = self.parse(b'{"choices":[{"message":{"role":"assistant","tool_calls":[{"id":"call-1","type":"function","function":{"name":"logs.search","arguments":"{\\"query\\":\\"x\\"}"}},{"id":"call-2","type":"function","function":{"name":"logs.tail","arguments":"{\\"lines\\":3}"}}]}}]}')
        self.assertEqual([call.name for call in one], ["logs.search"])
        self.assertEqual([call.name for call in multiple], ["logs.search", "logs.tail"])

    def test_parser_rejects_bad_and_boundary_response(self) -> None:
        good = b'{"choices":[{"message":{"role":"assistant","content":"done"}}]}'
        for raw in (
            b"{", b'{"choices":[],"choices":[]}', b'{"choices":[{"message":{"role":"assistant","content":"x","unknown":1}}]}',
            b'{"choices":[{"message":{"role":"assistant","content":"x","tool_calls":[]}}]}',
            b'{"choices":[{"message":{"role":"assistant","tool_calls":[{"id":"call-1","type":"function","function":{"name":"not.advertised","arguments":"{}"}}]}}]}',
            b'{"choices":[{"message":{"role":"assistant","tool_calls":[{"id":"call-1","type":"function","function":{"name":"logs.search","arguments":"{"}}]}}]}',
            b'{"choices":[{"message":{"role":"assistant","tool_calls":[{"id":"same","type":"function","function":{"name":"logs.search","arguments":"{\\"query\\":\\"x\\"}"}},{"id":"same","type":"function","function":{"name":"logs.search","arguments":"{\\"query\\":\\"x\\"}"}}]}}]}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ProviderError):
                self.parse(raw)
        exact = replace(DEFAULT_LIMITS, provider_response_bytes=len(good))
        self.assertEqual(parse_openai_compatible_response(good, advertised_tools=TOOLS, limits=exact).message.content, "done")
        with self.assertRaises(ProviderError) as raised:
            parse_openai_compatible_response(good, advertised_tools=TOOLS, limits=replace(exact, provider_response_bytes=len(good) - 1))
        self.assertEqual(raised.exception.failure.classification, FailureClass.OVERSIZED_RESPONSE)


class TransportAndAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["NATIVE_MCP_PHASE10_4_TOKEN"] = SENTINEL

    def _provider(self, server: FakeProviderServer, **changes: object) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(config(server.endpoint, **changes))

    def test_loopback_request_is_credential_free_and_retry_is_stable(self) -> None:
        with FakeProviderServer(FakeCase.RETRY_SUCCESS, openai_compatible=True) as server:
            result = self._provider(server).turn(request(), (), timeout_ms=1_000, cancellation=None)
            self.assertEqual(result.message.content, "synthetic guidance")
            self.assertEqual(server.request_count, 2)
            assert server.request_headers and server.request_bodies
            self.assertEqual([item["x-request-id"] for item in server.request_headers], ["req-10-4", "req-10-4"])
            self.assertTrue(all("authorization" not in item for item in server.request_headers))
            self.assertTrue(all(SENTINEL not in str(item) for item in server.request_headers))
            surfaces = (repr(result), str(server.request_bodies), repr(self._provider(server).config))
            self.assertTrue(all(SENTINEL not in surface for surface in surfaces))

    def test_loopback_never_reads_configured_credential_environment(self) -> None:
        class NoCredentialEnvironment:
            def get(self, _name: object, _default: object = None) -> object:
                raise AssertionError("loopback HTTP must not read configured credentials")

        with FakeProviderServer(FakeCase.FINAL, openai_compatible=True) as server:
            provider = self._provider(server)
            with patch("agent.native_mcp_agent.openai_compatible.os.environ", NoCredentialEnvironment()):
                result = provider.turn(request(), (), timeout_ms=1_000, cancellation=None)
            self.assertEqual(result.message.content, "synthetic guidance")
            assert server.request_headers
            self.assertNotIn("authorization", server.request_headers[0])

    def test_production_transport_is_the_only_credential_bearing_path(self) -> None:
        class RecordingTransport(OpenAICompatibleTransport):
            def __init__(self) -> None:
                super().__init__()
                self.credentials: list[str] = []

            def send_production(self, endpoint: ValidatedEndpoint, body: bytes, credential: str, **kwargs: object) -> bytes:
                if endpoint.scheme != "https" or kwargs["correlation_id"] != "req-10-4":
                    raise AssertionError("production credential was not confined to verified HTTPS")
                self.credentials.append(credential)
                return b'{"choices":[{"message":{"role":"assistant","content":"synthetic guidance"}}]}'

        transport = RecordingTransport()
        provider = OpenAICompatibleProvider(
            config("https://provider.example/v1/chat/completions", allow_loopback_http=False),
            transport,
        )
        result = provider.turn(request(), (), timeout_ms=1_000, cancellation=None)
        self.assertEqual(result.message.content, "synthetic guidance")
        self.assertEqual(transport.credentials, [SENTINEL])
        loopback = ValidatedEndpoint("http://127.0.0.1:1/v1", "http", "127.0.0.1", "127.0.0.1", 1, "/v1", True)
        with self.assertRaises(ProviderError) as raised:
            OpenAICompatibleTransport().send_production(loopback, b"{}", SENTINEL, limits=DEFAULT_LIMITS, correlation_id="req-10-4")
        self.assertEqual(raised.exception.failure.classification, FailureClass.ENDPOINT_POLICY_REJECTION)

    def test_verified_https_serializes_credential_only_as_authorization_header(self) -> None:
        response_body = b'{"choices":[{"message":{"role":"assistant","content":"synthetic guidance"}}]}'

        class CapturingSocket:
            def settimeout(self, _timeout: float) -> None:
                return

        class CapturingResponse:
            status = 200

            def __init__(self) -> None:
                self._remaining = response_body

            def getheader(self, name: str) -> str | None:
                return {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(response_body)),
                }.get(name)

            def read(self, _size: int) -> bytes:
                chunk, self._remaining = self._remaining, b""
                return chunk

        class CapturingConnection:
            def __init__(self) -> None:
                self.sock = CapturingSocket()
                self.headers: dict[str, str] | None = None

            def connect(self) -> None:
                return

            def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
                self.headers = dict(headers)
                self.method, self.path, self.body = method, path, body

            def getresponse(self) -> CapturingResponse:
                return CapturingResponse()

            def close(self) -> None:
                return

        endpoint = ValidatedEndpoint("https://provider.example/v1", "https", "provider.example", "203.0.113.1", 443, "/v1", False)
        connection = CapturingConnection()
        with patch("agent.native_mcp_agent.openai_compatible._VerifiedHTTPSConnection", return_value=connection), patch(
            "agent.native_mcp_agent.openai_compatible.resolve_production_transport_endpoint", return_value=endpoint,
        ):
            self.assertEqual(
                OpenAICompatibleTransport().send_production(endpoint, b"{}", SENTINEL, limits=DEFAULT_LIMITS, correlation_id="req-10-4"),
                response_body,
            )
        assert connection.headers is not None
        self.assertEqual(connection.headers["Authorization"], "Bearer " + SENTINEL)
        self.assertEqual(
            [name for name, value in connection.headers.items() if SENTINEL in value],
            ["Authorization"],
        )

    def test_synthetic_only_rejects_later_mcp_evidence_before_transmission(self) -> None:
        with FakeProviderServer(FakeCase.FINAL, openai_compatible=True) as server:
            with self.assertRaises(ProviderError) as raised:
                self._provider(server).turn(request(), (object(),), timeout_ms=1_000, cancellation=None)  # type: ignore[arg-type]
            self.assertEqual(raised.exception.failure.classification, FailureClass.LOCAL_POLICY_FAILURE)
            self.assertEqual(server.request_count, 0)

    def test_status_redirect_content_and_timeouts_are_classified(self) -> None:
        expected = {
            FakeCase.STATUS_400: FailureClass.HTTP_400_INVALID_REQUEST, FakeCase.STATUS_401: FailureClass.HTTP_401_AUTHENTICATION_FAILURE,
            FakeCase.STATUS_403: FailureClass.HTTP_403_AUTHORIZATION_FAILURE, FakeCase.STATUS_404: FailureClass.HTTP_404_ENDPOINT_OR_MODEL_NOT_FOUND,
            FakeCase.STATUS_408: FailureClass.HTTP_408_REQUEST_TIMEOUT, FakeCase.STATUS_413: FailureClass.HTTP_413_PAYLOAD_TOO_LARGE,
            FakeCase.STATUS_422: FailureClass.HTTP_422_SEMANTIC_REJECTION, FakeCase.STATUS_429: FailureClass.HTTP_429_RATE_LIMITED,
            FakeCase.STATUS_409: FailureClass.OTHER_PERMANENT_4XX, FakeCase.STATUS_500: FailureClass.TRANSIENT_5XX,
            FakeCase.REDIRECT: FailureClass.REDIRECT_REJECTED, FakeCase.INVALID_CONTENT_TYPE: FailureClass.INVALID_CONTENT_TYPE,
            FakeCase.CONNECTION_CLOSE: FailureClass.DNS_OR_CONNECTION_FAILURE,
        }
        for case, kind in expected.items():
            with self.subTest(case=case), FakeProviderServer(case, openai_compatible=True) as server:
                with self.assertRaises(ProviderError) as raised:
                    self._provider(server, limits=replace(DEFAULT_LIMITS, provider_attempt_count=1)).turn(request(), (), timeout_ms=1_000, cancellation=None)
                self.assertEqual(raised.exception.failure.classification, kind)
        for case, limits, kind in (
            (FakeCase.DELAYED, replace(DEFAULT_LIMITS, provider_read_inactivity_timeout_ms=10, provider_total_timeout_ms=500), FailureClass.READ_TIMEOUT),
            (FakeCase.DELAYED, replace(DEFAULT_LIMITS, provider_read_inactivity_timeout_ms=500, provider_total_timeout_ms=10), FailureClass.TOTAL_REQUEST_TIMEOUT),
        ):
            with self.subTest(case=case, kind=kind), FakeProviderServer(case, openai_compatible=True) as server:
                with self.assertRaises(ProviderError) as raised:
                    self._provider(server, limits=limits).turn(request(), (), timeout_ms=1_000, cancellation=None)
                self.assertEqual(raised.exception.failure.classification, kind)

    def test_missing_credential_no_eager_load_tls_and_authority_marker(self) -> None:
        os.environ.pop("NATIVE_MCP_PHASE10_4_TOKEN", None)
        cfg = config("https://provider.example/v1/chat/completions", allow_loopback_http=False)
        provider = OpenAICompatibleProvider(cfg)
        with self.assertRaises(ProviderError) as raised:
            provider.turn(request(), (), timeout_ms=10, cancellation=None)
        self.assertEqual(raised.exception.failure.classification, FailureClass.CREDENTIAL_UNAVAILABLE)
        self.assertIsInstance(provider, BoundedProvider)
        self.assertIsInstance(ScriptedProvider(()), BoundedProvider)
        with self.assertRaises(ProviderError):
            Orchestrator(McpStdioClient("/bin/false", parent_environment={}), object())  # type: ignore[arg-type]

        class CertFailure(OpenAICompatibleTransport):
            def _one_attempt(self, *_args: object, **_kwargs: object):
                raise ssl.SSLCertVerificationError("withheld")
        os.environ["NATIVE_MCP_PHASE10_4_TOKEN"] = SENTINEL
        endpoint = ValidatedEndpoint("https://provider.example/v1", "https", "provider.example", "203.0.113.1", 443, "/v1", False)
        with self.assertRaises(ProviderError) as tls:
            with patch("agent.native_mcp_agent.openai_compatible.resolve_production_transport_endpoint", return_value=endpoint):
                CertFailure().send_production(endpoint, b"{}", SENTINEL, limits=DEFAULT_LIMITS, correlation_id="req-10-4")
        self.assertEqual(tls.exception.failure.classification, FailureClass.TLS_VERIFICATION_FAILURE)


if __name__ == "__main__":
    unittest.main()
