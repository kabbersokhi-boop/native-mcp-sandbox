#!/usr/bin/env python3
"""Focused Phase 10.1 security-contract regressions."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.native_mcp_agent import ModelIdentifier  # noqa: E402
from agent.native_mcp_agent.contracts import (  # noqa: E402
    AdvertisedTool, EvidenceProvenance, MessageRole, ProviderConfig, ProviderMessage,
    ProviderRequest, ProviderToolCallProposal, RequestCorrelationId, ToolCallId,
    parse_provider_response,
)
from agent.native_mcp_agent.environment import build_child_environment  # noqa: E402
from agent.native_mcp_agent.errors import FailureClass, ProviderError, failure  # noqa: E402
from agent.native_mcp_agent.limits import DEFAULT_LIMITS  # noqa: E402
from agent.native_mcp_agent.transcript import TranscriptEvent, parse_transcript  # noqa: E402
from agent.native_mcp_agent.transport import LoopbackFakeTransport  # noqa: E402
from tests.fake_provider import FakeCase, FakeProviderServer  # noqa: E402


TOOL = AdvertisedTool(
    "logs.search",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": [], "additionalProperties": False},
)


def request(model: str = "synthetic-model") -> ProviderRequest:
    return ProviderRequest(
        model, (ProviderMessage(MessageRole.USER, "synthetic"),), (TOOL,), 128,
        RequestCorrelationId("req-10-1"),
    )


class IdentifierTests(unittest.TestCase):
    def test_canonical_control_ids_and_legacy_hashing(self) -> None:
        self.assertEqual(RequestCorrelationId("req-10-1"), "req-10-1")
        self.assertEqual(RequestCorrelationId("req-123"), "req-123")
        self.assertRegex(RequestCorrelationId.new(), r"^req-[0-9]+$")
        self.assertEqual(ToolCallId("call-1"), "call-1")
        self.assertTrue(str(ToolCallId("provider-call-17")).startswith("call-"))
        self.assertEqual(ToolCallId("provider-call-17"), ToolCallId("provider-call-17"))
        for value in ("abc", "request-1", "req-user", "req-1.2", "req-1/2"):
            with self.subTest(value=value), self.assertRaises(ProviderError):
                RequestCorrelationId(value)
        for value in ("authorization-token", "api-key-abc", "user@host", "/tmp/call", "header:path"):
            with self.subTest(value=value), self.assertRaises(ProviderError):
                ToolCallId(value)

    def test_duplicate_detection_uses_canonical_provider_id(self) -> None:
        raw = b'{"toolCalls":[{"id":"legacy-id","name":"logs.search","arguments":"{}"},{"id":"legacy-id","name":"logs.search","arguments":"{}"}]}'
        with self.assertRaises(ProviderError) as raised:
            parse_provider_response(raw, advertised_tools=(TOOL,))
        self.assertEqual(raised.exception.failure.classification, FailureClass.REPLAY_OR_DUPLICATE_PROPOSAL)

    def test_transcripts_accept_only_canonical_proposal_ids(self) -> None:
        event = TranscriptEvent(
            "event", "adapter", ModelIdentifier("provider:model"), RequestCorrelationId("req-10-1"),
            EvidenceProvenance.LOCAL_CONTROL_EVENT, proposal_ids=(ToolCallId("call-1"),),
        )
        self.assertEqual(parse_transcript(event.to_json_bytes()).proposal_ids, (ToolCallId("call-1"),))
        raw = json.loads(event.to_json_bytes())
        raw["proposalIds"] = ["legacy-id"]
        with self.assertRaises(ProviderError):
            parse_transcript(json.dumps(raw).encode())


class ModelAndProxyTests(unittest.TestCase):
    def test_shared_model_identifier_contract(self) -> None:
        for value in ("synthetic-model", "organization/model-name", "provider:model", "m"):
            with self.subTest(value=value):
                config = ProviderConfig("https://provider.example/v1", value)
                req = request(value)
                event = TranscriptEvent("event", "adapter", value, RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT)
                self.assertIsInstance(config.model, ModelIdentifier)
                self.assertIsInstance(req.model, ModelIdentifier)
                self.assertIsInstance(event.model, ModelIdentifier)
                self.assertEqual(json.loads(req.to_json_bytes())["model"], value)
                self.assertEqual(json.loads(event.to_json_bytes())["model"], value)
        for value in ("", "organization//model", "organization/ model", "/absolute", "https://host/model", "user:pass@model", "api-key-secret", "model\nname", "x" * 257):
            with self.subTest(value=value), self.assertRaises(ProviderError):
                ModelIdentifier(value)

    def test_credential_free_proxies_and_bounded_no_proxy(self) -> None:
        parent = {
            "HTTP_PROXY": "http://proxy.example:8080/",
            "HTTPS_PROXY": "https://192.0.2.10:443",
            "ALL_PROXY": "http://[2001:db8::10]:3128",
            "NO_PROXY": "*,.example.com,example.org:8443,192.0.2.1,[2001:db8::1]:443",
        }
        result = build_child_environment(parent, tuple(parent), allow_proxy=True, provider_child=False)
        self.assertEqual(result, parent)
        invalid = (
            "http://user:pass@proxy.example:8080", "http://proxy.example", "ftp://proxy.example:8080",
            "http://proxy.example:notaport", "http://proxy.example:8080/path", "http://proxy.example:8080?q=x",
            "http://proxy.example:8080#x", "http://proxy.example:8080\\x",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ProviderError):
                build_child_environment({"HTTP_PROXY": value}, ("HTTP_PROXY",), allow_proxy=True, provider_child=False)
        invalid_no_proxy = ("", "example.com,,example.org", "example.com example.org", "https://example.org", "user:pass@example.org", "2001:db8::1", "example.org:bad", "[bad]", "example.org/")
        for value in invalid_no_proxy:
            with self.subTest(value=value), self.assertRaises(ProviderError):
                build_child_environment({"NO_PROXY": value}, ("NO_PROXY",), allow_proxy=True, provider_child=False)
        with self.assertRaises(ProviderError):
            build_child_environment({"HTTP_PROXY": "http://proxy.example:8080"}, ("HTTP_PROXY",), allow_proxy=True)


class FailureAndImmutabilityTests(unittest.TestCase):
    def test_independent_secret_sentinels_never_cross_boundaries(self) -> None:
        sentinels = {
            "event": "event-secret-sentinel",
            "adapter": "adapter-token-sentinel",
            "model": "model-secret-sentinel",
            "correlation": "req-token-sentinel",
            "proposal": "authorization-sentinel",
            "metadata_key": "metadata-secret-key",
            "metadata_value": "metadata-token-value",
            "failure_class": "failure-class-sentinel",
            "failure_detail": "failure-detail-sentinel",
        }
        observations: list[str] = []
        for field_name in ("event", "adapter", "model", "correlation"):
            values = {"event": "event", "adapter": "adapter", "model": "synthetic-model", "correlation": RequestCorrelationId("req-10-1")}
            values[field_name] = sentinels[field_name]
            try:
                TranscriptEvent(values["event"], values["adapter"], values["model"], values["correlation"], EvidenceProvenance.LOCAL_CONTROL_EVENT)  # type: ignore[arg-type]
            except ProviderError as error:
                observations.extend((str(error), repr(error), repr(error.failure.__dict__)))
        for value in (sentinels["proposal"],):
            try:
                ToolCallId(value)
            except ProviderError as error:
                observations.extend((str(error), repr(error), repr(error.failure.__dict__)))
        try:
            TranscriptEvent("event", "adapter", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, metadata={sentinels["metadata_key"]: "safe"})
        except ProviderError as error:
            observations.extend((str(error), repr(error), repr(error.failure.__dict__)))
        try:
            TranscriptEvent("event", "adapter", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, metadata={"mode": sentinels["metadata_value"]})
        except ProviderError as error:
            observations.extend((str(error), repr(error), repr(error.failure.__dict__)))
        classified = failure(sentinels["failure_class"], sentinels["failure_detail"])  # type: ignore[arg-type]
        observations.extend((str(ProviderError(classified)), repr(ProviderError(classified)), repr(classified.__dict__)))
        for sentinel in sentinels.values():
            self.assertNotIn(sentinel, " ".join(observations))

    def test_failure_output_is_closed(self) -> None:
        sentinel = "FAILURE_DETAIL_SENTINEL"
        classified = failure(FailureClass.HTTP_429_RATE_LIMITED, sentinel, status_code=429, retry_after_ms=50, attempt=1)
        error = ProviderError(classified)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                raise error
            except ProviderError:
                pass
        event = TranscriptEvent("failure", "adapter", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, failure_class=classified.classification)
        output = " ".join((str(error), repr(error), repr(classified), repr(classified.__dict__), out.getvalue(), err.getvalue(), event.to_json_bytes().decode()))
        self.assertNotIn(sentinel, output)
        self.assertEqual(classified.detail, "")
        self.assertNotIn(sentinel, str(classified.__dict__))

    def test_recursive_freezing_and_stable_action_identity(self) -> None:
        arguments = {"nested": {"values": ["secret-value"]}}
        proposal = ProviderToolCallProposal(ToolCallId("call-1"), "logs.search", arguments)
        before_bytes = proposal.canonical_argument_bytes
        before_identity = proposal.action_identity
        arguments["nested"]["values"].append("mutated")
        arguments["nested"]["new"] = "caller mutation"
        self.assertEqual(proposal.canonical_argument_bytes, before_bytes)
        self.assertEqual(proposal.action_identity, before_identity)
        self.assertEqual(proposal.arguments["nested"]["values"], ("secret-value",))
        with self.assertRaises(TypeError):
            proposal.arguments["nested"] = {}  # type: ignore[index]
        schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        advertised = AdvertisedTool("immutable", schema)
        schema["properties"]["late"] = {"type": "string"}
        self.assertNotIn("late", advertised.parameters["properties"])
        metadata = {"mode": "synthetic"}
        event = TranscriptEvent("event", "adapter", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT, metadata=metadata)
        metadata["mode"] = "mutated"
        self.assertEqual(event.metadata["mode"], "synthetic")
        with self.assertRaises(TypeError):
            event.metadata["mode"] = "mutated"  # type: ignore[index]

    def test_serialization_revalidates_tampered_scalars(self) -> None:
        req = request()
        object.__setattr__(req, "model", "https://secret.invalid/model")
        with self.assertRaises(ProviderError):
            req.to_json_bytes()
        event = TranscriptEvent("event", "adapter", "synthetic-model", RequestCorrelationId("req-10-1"), EvidenceProvenance.LOCAL_CONTROL_EVENT)
        object.__setattr__(event, "correlation_id", "secret-correlation")
        with self.assertRaises(ProviderError):
            event.to_json_bytes()


class RetryAfterTests(unittest.TestCase):
    def test_retry_after_valid_missing_malformed_and_excessive(self) -> None:
        limits = replace(DEFAULT_LIMITS, provider_attempt_count=2, retry_backoff_ms=7, retry_after_ms=1_000)
        for case, expected_sleep in (
            (FakeCase.RETRY_AFTER, ()),
            (FakeCase.STATUS_429, (0.007,)),
            (FakeCase.MALFORMED_RETRY_AFTER, (0.007,)),
            (FakeCase.EXCESSIVE_RETRY_AFTER, (0.007,)),
        ):
            sleeps: list[float] = []
            with self.subTest(case=case), FakeProviderServer(case) as provider:
                transport = LoopbackFakeTransport(sleep=sleeps.append)
                with self.assertRaises(ProviderError) as raised:
                    transport.send(provider.validated_endpoint(), request(), limits=limits, correlation_id="req-10-1")
            self.assertEqual(tuple(sleeps), expected_sleep)
            self.assertNotIn("not-a-delay", str(raised.exception))
            self.assertNotIn("not-a-delay", repr(raised.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
