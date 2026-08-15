"""Bounded, optional OpenAI-compatible non-streaming provider adapter.

This module is intentionally external-agent-only.  It has no MCP process
authority and exposes a small project-owned ``BoundedProvider`` implementation
to the serial orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
import http.client
import json
import os
import re
import socket
import ssl
import time
from typing import Any, Callable, Mapping, Sequence

from .contracts import (
    AdvertisedTool, MessageRole, ModelIdentifier, ProviderFinalMessage,
    ProviderMessage, ProviderRequest, ProviderToolCallProposal, ToolCallId,
    _bounded_text, _closed_object, parse_closed_json, parse_provider_response,
)
from .endpoint_policy import (
    ValidatedEndpoint, redirect_rejection, resolve_production_transport_endpoint,
    validate_fake_loopback_endpoint, validate_loopback_transport_endpoint,
    validate_production_endpoint,
)
from .errors import ClassifiedFailure, FailureClass, ProviderError, failure, http_failure
from .limits import DEFAULT_LIMITS, Limits
from .mcp_orchestrator import BoundedProvider, Cancellation, Evidence
from .retry import decide_retry
from .transport import _retry_after


_CREDENTIAL_ENV = re.compile(r"^NATIVE_MCP_[A-Z0-9_]{1,96}$")
_JSON_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class AuthorizedSyntheticMessage(ProviderMessage):
    """A provider message issued by this project's synthetic-egress authority.

    The marker is deliberately non-serializable and has no caller-supplied
    constructor argument.  Plain ``ProviderMessage`` values, including values
    with identical text, do not carry this authority.
    """

    _synthetic_authorization: object | None = field(default=None, init=False, repr=False, compare=False)


def _synthetic_message_authority() -> tuple[
    Callable[[MessageRole, str], AuthorizedSyntheticMessage],
    Callable[[ProviderMessage], bool],
]:
    """Keep the capability identity private to the project-owned factory."""
    issuer = object()

    def authorize(role: MessageRole, content: str) -> AuthorizedSyntheticMessage:
        message = AuthorizedSyntheticMessage(role, content)
        object.__setattr__(message, "_synthetic_authorization", issuer)
        return message

    def is_authorized(message: ProviderMessage) -> bool:
        return (
            type(message) is AuthorizedSyntheticMessage
            and message._synthetic_authorization is issuer
        )

    return authorize, is_authorized


authorized_synthetic_message, _is_authorized_synthetic_message = _synthetic_message_authority()


def _closed_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
    allowed = {
        "endpoint", "model", "credentialEnv", "verifyTls", "allowLoopbackHttp",
        "dataFlow", "limits",
    }
    if not isinstance(value, Mapping) or set(value) - allowed or {"endpoint", "model", "credentialEnv"} - set(value):
        raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "adapter configuration is not closed"))
    return value


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Closed configuration; credentials are named, never stored here."""

    endpoint: str
    model: ModelIdentifier | str
    credential_env: str
    verify_tls: bool = True
    allow_loopback_http: bool = False
    data_flow: str = "synthetic-only"
    limits: Limits = DEFAULT_LIMITS

    def __post_init__(self) -> None:
        try:
            model = self.model if isinstance(self.model, ModelIdentifier) else ModelIdentifier(self.model)
        except ProviderError as error:
            raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "configured model is invalid")) from error
        if not isinstance(self.endpoint, str) or not self.endpoint or len(self.endpoint.encode("utf-8", "strict")) > 2_048:
            raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "configured endpoint is invalid"))
        if not isinstance(self.credential_env, str) or not _CREDENTIAL_ENV.fullmatch(self.credential_env):
            raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "credential source is invalid"))
        if self.verify_tls is not True:
            raise ProviderError(failure(FailureClass.TLS_VERIFICATION_FAILURE, "TLS verification is mandatory"))
        if not isinstance(self.allow_loopback_http, bool) or self.data_flow != "synthetic-only" or not isinstance(self.limits, Limits):
            raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "adapter configuration is invalid"))
        object.__setattr__(self, "model", model)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpenAICompatibleConfig":
        raw = _closed_config(value)
        limits = DEFAULT_LIMITS
        if "limits" in raw:
            supplied = raw["limits"]
            names = {item.name for item in fields(Limits)}
            if not isinstance(supplied, Mapping) or set(supplied) - names:
                raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "adapter limits are not closed"))
            try:
                limits = replace(DEFAULT_LIMITS, **dict(supplied))
            except (TypeError, ValueError, ProviderError):
                raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "adapter limits are invalid")) from None
        return cls(
            endpoint=raw["endpoint"], model=raw["model"], credential_env=raw["credentialEnv"],
            verify_tls=raw.get("verifyTls", True), allow_loopback_http=raw.get("allowLoopbackHttp", False),
            data_flow=raw.get("dataFlow", "synthetic-only"), limits=limits,
        )

    def validated_endpoint(self) -> ValidatedEndpoint:
        if self.allow_loopback_http:
            return validate_fake_loopback_endpoint(self.endpoint, allow_loopback_http=True)
        return validate_production_endpoint(self.endpoint, verify_tls=self.verify_tls)


def openai_request_bytes(request: ProviderRequest, config: OpenAICompatibleConfig) -> bytes:
    """Map only the provider-neutral contract into OpenAI-compatible JSON."""
    if not isinstance(request, ProviderRequest) or request.model != config.model:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "provider request model does not match configured model"))
    # Phase 10.4 has only a synthetic-only egress mode.  The authorization is
    # an opaque project capability, never an inference from message text.
    if any(not _is_authorized_synthetic_message(message) for message in request.messages):
        raise ProviderError(failure(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "synthetic-only request is not project-authorized"))
    # Reapply all local cardinality/schema/byte checks before mapping.
    request.to_json_bytes(config.limits)
    tools = [
        {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}
        for tool in request.tools
    ]
    value: dict[str, Any] = {
        "model": str(config.model),
        "messages": [{"role": item.role.value, "content": item.content} for item in request.messages],
        "tools": tools,
        "tool_choice": "auto" if tools else "none",
        "max_tokens": request.max_output_tokens,
        "stream": False,
    }
    if request.generation.temperature is not None:
        value["temperature"] = request.generation.temperature
    if request.generation.top_p is not None:
        value["top_p"] = request.generation.top_p
    if request.generation.seed is not None:
        value["seed"] = request.generation.seed
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > config.limits.provider_request_bytes:
        raise ProviderError(failure(FailureClass.REQUEST_TOO_LARGE, "mapped request exceeds byte limit"))
    return encoded


def _openai_closed_object(value: Any, allowed: set[str], required: set[str], label: str) -> Mapping[str, Any]:
    try:
        return _closed_object(value, allowed, required, label)
    except ProviderError as error:
        raise ProviderError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "OpenAI-compatible response shape is unsupported")) from error


def parse_openai_compatible_response(
    raw: bytes,
    *,
    advertised_tools: Sequence[AdvertisedTool],
    limits: Limits = DEFAULT_LIMITS,
) -> ProviderFinalMessage | tuple[ProviderToolCallProposal, ...]:
    """Closed parser which discards only explicit, common provider envelope fields."""
    value = parse_closed_json(raw, limits)
    top = _openai_closed_object(value, {"id", "object", "created", "model", "choices", "usage", "system_fingerprint"}, {"choices"}, "OpenAI response")
    choices = top["choices"]
    if not isinstance(choices, list) or len(choices) != 1:
        raise ProviderError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "OpenAI choices are unsupported"))
    choice = _openai_closed_object(choices[0], {"index", "message", "finish_reason", "logprobs"}, {"message"}, "OpenAI choice")
    message = _openai_closed_object(choice["message"], {"role", "content", "tool_calls", "refusal"}, {"role"}, "OpenAI message")
    if message["role"] != "assistant":
        raise ProviderError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "OpenAI message role is unsupported"))
    has_text = "content" in message and message["content"] is not None
    has_calls = "tool_calls" in message and message["tool_calls"] is not None
    if has_text and has_calls:
        raise ProviderError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "mixed final text and tool calls are unsupported"))
    if has_text:
        content = _bounded_text(message["content"], "OpenAI final content", limits.message_bytes, FailureClass.UNSUPPORTED_PROVIDER_CONTENT)
        return ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, content))
    if not has_calls or not isinstance(message["tool_calls"], list) or not message["tool_calls"]:
        raise ProviderError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "OpenAI content is unsupported"))
    calls: list[dict[str, str]] = []
    for item in message["tool_calls"]:
        call = _openai_closed_object(item, {"id", "type", "function"}, {"id", "type", "function"}, "OpenAI tool call")
        if call["type"] != "function":
            raise ProviderError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "OpenAI tool type is unsupported"))
        function = _openai_closed_object(call["function"], {"name", "arguments"}, {"name", "arguments"}, "OpenAI function")
        if not isinstance(call["id"], str) or not isinstance(function["name"], str) or not isinstance(function["arguments"], str):
            raise ProviderError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "OpenAI tool call is malformed"))
        calls.append({"id": call["id"], "name": function["name"], "arguments": function["arguments"]})
    # Delegate neutral allowlist, duplicate-ID, arguments JSON, and closed
    # argument-schema enforcement to the existing project-owned contract.
    neutral = json.dumps({"toolCalls": calls}, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return parse_provider_response(neutral, advertised_tools=advertised_tools, limits=limits)


class _VerifiedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, public_host: str, connect_host: str, port: int, timeout: float) -> None:
        super().__init__(public_host, port, timeout=timeout, context=ssl.create_default_context())
        self._connect_host = connect_host

    def connect(self) -> None:
        self.sock = socket.create_connection((self._connect_host, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class OpenAICompatibleTransport:
    """HTTPS/loopback bounded request transport.  Redirects are never followed."""

    def __init__(self, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.sleep, self.clock = sleep, clock

    def send_production(self, endpoint: ValidatedEndpoint, body: bytes, credential: str, *, limits: Limits, correlation_id: str, deadline: float | None = None) -> bytes:
        """Send a credential-bearing request only to a verified HTTPS endpoint."""
        if not isinstance(endpoint, ValidatedEndpoint) or endpoint.loopback_only or endpoint.scheme != "https":
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "credential transport requires production HTTPS"))
        if not isinstance(credential, str) or not credential:
            raise ProviderError(failure(FailureClass.CREDENTIAL_UNAVAILABLE, "credential is unavailable"))
        return self._send(endpoint, body, credential, limits=limits, correlation_id=correlation_id, deadline=deadline)

    def send_loopback(self, endpoint: ValidatedEndpoint, body: bytes, *, limits: Limits, correlation_id: str, deadline: float | None = None) -> bytes:
        """Send an explicitly test-only loopback request without credentials."""
        if not isinstance(endpoint, ValidatedEndpoint) or endpoint.loopback_only is not True:
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "credential-free transport requires loopback HTTP"))
        validate_loopback_transport_endpoint(endpoint)
        return self._send(endpoint, body, None, limits=limits, correlation_id=correlation_id, deadline=deadline)

    def _send(self, endpoint: ValidatedEndpoint, body: bytes, credential: str | None, *, limits: Limits, correlation_id: str, deadline: float | None = None) -> bytes:
        if not isinstance(body, bytes) or len(body) > limits.provider_request_bytes:
            raise ProviderError(failure(FailureClass.REQUEST_TOO_LARGE, "request exceeds byte limit"))
        if not isinstance(correlation_id, str) or not correlation_id.startswith("req-"):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "correlation is invalid"))
        if not isinstance(endpoint, ValidatedEndpoint):
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "provider endpoint is invalid"))
        if endpoint.loopback_only:
            validate_loopback_transport_endpoint(endpoint)
            if credential is not None:
                raise ProviderError(failure(FailureClass.LOCAL_POLICY_FAILURE, "loopback transport forbids credentials"))
        elif not isinstance(credential, str) or not credential:
            raise ProviderError(failure(FailureClass.CREDENTIAL_UNAVAILABLE, "credential is unavailable"))
        now = self.clock()
        deadline_at = now + limits.provider_total_timeout_ms / 1000.0
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or deadline <= now:
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline is invalid"))
            deadline_at = min(deadline_at, float(deadline))
        for attempt in range(1, limits.provider_attempt_count + 1):
            if self.clock() >= deadline_at:
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline expired", attempt=attempt - 1))
            try:
                # DNS is refreshed immediately before every production socket
                # connection, including a retry after a transient failure.
                attempt_endpoint = endpoint if endpoint.loopback_only else resolve_production_transport_endpoint(endpoint)
                response, content_type, status, retry_after = self._one_attempt(attempt_endpoint, body, credential, correlation_id, limits, deadline_at)
                if 300 <= status < 400:
                    raise ProviderError(redirect_rejection())
                if not 200 <= status < 300:
                    raise ProviderError(http_failure(status, retry_after_ms=retry_after))
                if content_type is None or content_type.lower().split(";", 1)[0].strip() != _JSON_CONTENT_TYPE:
                    raise ProviderError(failure(FailureClass.INVALID_CONTENT_TYPE, "provider content type is invalid"))
                return response
            except ProviderError as error:
                last = error.failure
            except ssl.SSLCertVerificationError:
                last = failure(FailureClass.TLS_VERIFICATION_FAILURE, "certificate verification failed")
            except ssl.CertificateError:
                last = failure(FailureClass.TLS_VERIFICATION_FAILURE, "certificate verification failed")
            except socket.timeout:
                last = failure(FailureClass.TOTAL_REQUEST_TIMEOUT if self.clock() >= deadline_at else FailureClass.READ_TIMEOUT, "response timed out")
            except TimeoutError:
                last = failure(FailureClass.CONNECT_TIMEOUT, "connection timed out")
            except (socket.gaierror, ConnectionError, OSError, http.client.HTTPException):
                last = failure(FailureClass.DNS_OR_CONNECTION_FAILURE, "connection failed")
            except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError):
                last = failure(FailureClass.MALFORMED_HTTP_RESPONSE, "provider HTTP response is malformed")
            last = replace(last, attempt=attempt)
            remaining_ms = max(0, int((deadline_at - self.clock()) * 1000))
            decision = decide_retry(last, completed_attempts=attempt, remaining_ms=remaining_ms, limits=limits)
            if not decision.eligible:
                if last.retryable and attempt >= limits.provider_attempt_count and limits.provider_attempt_count > 1:
                    raise ProviderError(failure(FailureClass.RETRY_EXHAUSTED, "retry budget exhausted", attempt=attempt))
                raise ProviderError(last)
            if decision.delay_ms / 1000.0 > deadline_at - self.clock():
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "retry exceeds deadline", attempt=attempt))
            self.sleep(decision.delay_ms / 1000.0)
        raise ProviderError(failure(FailureClass.RETRY_EXHAUSTED, "retry budget exhausted"))

    def _one_attempt(self, endpoint: ValidatedEndpoint, body: bytes, credential: str, correlation_id: str, limits: Limits, deadline: float) -> tuple[bytes, str | None, int, int | None]:
        timeout = min(deadline - self.clock(), limits.provider_connect_timeout_ms / 1000.0)
        if timeout <= 0:
            raise ProviderError(failure(FailureClass.CONNECT_TIMEOUT, "connection deadline expired"))
        connection: http.client.HTTPConnection
        if endpoint.loopback_only:
            connection = http.client.HTTPConnection(endpoint.connect_host, endpoint.port, timeout=timeout)
        else:
            connection = _VerifiedHTTPSConnection(endpoint.host, endpoint.connect_host, endpoint.port, timeout)
        try:
            try:
                connection.connect()
            except (socket.timeout, TimeoutError):
                raise ProviderError(failure(FailureClass.CONNECT_TIMEOUT, "connection timed out")) from None
            headers = {"Accept": _JSON_CONTENT_TYPE, "Content-Type": _JSON_CONTENT_TYPE, "Content-Length": str(len(body)), "X-Request-ID": correlation_id}
            if credential is not None:
                headers["Authorization"] = "Bearer " + credential
            connection.request("POST", endpoint.path, body=body, headers=headers)
            self._set_read_timeout(connection, deadline, limits)
            response = connection.getresponse()
            status = response.status
            if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                raise ProviderError(failure(FailureClass.MALFORMED_HTTP_RESPONSE, "HTTP status is malformed"))
            content_type, retry_after = response.getheader("Content-Type"), _retry_after(response.getheader("Retry-After"), limits)
            if 300 <= status < 400:
                return b"", content_type, status, retry_after
            declared = response.getheader("Content-Length")
            if declared is not None:
                if not isinstance(declared, str) or not re.fullmatch(r"[0-9]+", declared):
                    raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "response length is malformed"))
                if int(declared) > limits.provider_response_bytes:
                    raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "response is oversized"))
            chunks = bytearray()
            while True:
                self._set_read_timeout(connection, deadline, limits)
                chunk = response.read(min(8192, limits.provider_response_bytes - len(chunks) + 1))
                if not isinstance(chunk, bytes):
                    raise ProviderError(failure(FailureClass.MALFORMED_HTTP_RESPONSE, "response body is malformed"))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > limits.provider_response_bytes:
                    raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "response is oversized"))
            if declared is not None and len(chunks) != int(declared):
                raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "response is truncated"))
            return bytes(chunks), content_type, status, retry_after
        finally:
            try:
                connection.close()
            except (AttributeError, OSError, TypeError, ValueError):
                pass

    def _set_read_timeout(self, connection: http.client.HTTPConnection, deadline: float, limits: Limits) -> None:
        remaining = min(deadline - self.clock(), limits.provider_read_inactivity_timeout_ms / 1000.0)
        if remaining <= 0:
            raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline expired"))
        if connection.sock is not None:
            connection.sock.settimeout(remaining)


@dataclass
class OpenAICompatibleProvider(BoundedProvider):
    config: OpenAICompatibleConfig
    transport: OpenAICompatibleTransport | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config, OpenAICompatibleConfig):
            raise ProviderError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "adapter config is invalid"))
        if self.transport is None:
            self.transport = OpenAICompatibleTransport()
        if not isinstance(self.transport, OpenAICompatibleTransport):
            raise ProviderError(failure(FailureClass.LOCAL_POLICY_FAILURE, "adapter transport is not project-owned"))

    def turn(self, request: ProviderRequest, evidence: tuple[Evidence, ...], *, timeout_ms: int, cancellation: Cancellation | None) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]:
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline is invalid"))
        if cancellation is not None and cancellation.is_set():
            raise ProviderError(failure(FailureClass.CANCELLED, "provider cancelled"))
        # This PR has no approved host-evidence egress mode.  Tool results can
        # never silently become provider input on later turns.
        if evidence:
            raise ProviderError(failure(FailureClass.LOCAL_POLICY_FAILURE, "synthetic-only provider rejects evidence"))
        endpoint = self.config.validated_endpoint()
        body = openai_request_bytes(request, self.config)
        deadline = time.monotonic() + timeout_ms / 1000.0
        assert self.transport is not None
        if endpoint.loopback_only:
            # This branch deliberately has no reference to the configured
            # credential source.  The test harness cannot read or transmit it.
            raw = self.transport.send_loopback(endpoint, body, limits=self.config.limits, correlation_id=str(request.correlation_id), deadline=deadline)
        else:
            credential = self._load_production_credential()
            raw = self.transport.send_production(endpoint, body, credential, limits=self.config.limits, correlation_id=str(request.correlation_id), deadline=deadline)
        if cancellation is not None and cancellation.is_set():
            raise ProviderError(failure(FailureClass.CANCELLED, "provider cancelled"))
        return parse_openai_compatible_response(raw, advertised_tools=request.tools, limits=self.config.limits)

    def _load_production_credential(self) -> str:
        """Load the configured credential at explicit verified-HTTPS execution only."""
        credential = os.environ.get(self.config.credential_env)
        if (
            not isinstance(credential, str) or not credential
            or len(credential.encode("utf-8", "strict")) > 16_384
            or any(ord(char) < 0x20 or ord(char) == 0x7f for char in credential)
        ):
            raise ProviderError(failure(FailureClass.CREDENTIAL_UNAVAILABLE, "credential is unavailable"))
        return credential
