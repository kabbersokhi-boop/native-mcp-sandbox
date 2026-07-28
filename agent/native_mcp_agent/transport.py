"""Bounded non-streaming transport for the loopback fake only."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import socket
import time
from typing import Callable, Protocol

from .contracts import ProviderRequest, ProviderFinalMessage, ProviderToolCallProposal, parse_provider_response
from .endpoint_policy import ValidatedEndpoint, redirect_rejection
from .errors import ClassifiedFailure, FailureClass, ProviderError, failure, http_failure
from .limits import DEFAULT_LIMITS, Limits
from .retry import RetryDecision, decide_retry


ProviderResponse = ProviderFinalMessage | tuple[ProviderToolCallProposal, ...]


class NonStreamingTransport(Protocol):
    def send(
        self,
        endpoint: ValidatedEndpoint,
        request: ProviderRequest,
        *,
        limits: Limits = DEFAULT_LIMITS,
        correlation_id: str,
        deadline: float | None = None,
    ) -> ProviderResponse:
        ...


@dataclass
class LoopbackFakeTransport:
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def send(
        self,
        endpoint: ValidatedEndpoint,
        request: ProviderRequest,
        *,
        limits: Limits = DEFAULT_LIMITS,
        correlation_id: str,
        deadline: float | None = None,
    ) -> ProviderResponse:
        if not endpoint.loopback_only or endpoint.scheme != "http":
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "transport accepts loopback fake endpoints only"))
        if str(request.correlation_id) != correlation_id:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transport correlation ID mismatch"))
        body = request.to_json_bytes(limits)
        deadline_at = self.clock() + limits.provider_total_timeout_ms / 1_000.0
        if deadline is not None:
            if not isinstance(deadline, (int, float)) or deadline <= self.clock():
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline is invalid or expired"))
            deadline_at = min(deadline_at, float(deadline))
        last: ClassifiedFailure | None = None
        for attempt in range(1, limits.provider_attempt_count + 1):
            remaining = deadline_at - self.clock()
            if remaining <= 0:
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider total deadline expired", attempt=attempt - 1))
            try:
                response_body, content_type, status, retry_after = self._one_attempt(endpoint, body, limits, deadline_at)
                if status in {301, 302, 303, 307, 308}:
                    last = redirect_rejection(None)
                elif status < 200 or status >= 300:
                    last = http_failure(status, retry_after_ms=retry_after)
                else:
                    if content_type is None or content_type.lower().split(";", 1)[0].strip() != "application/json":
                        raise ProviderError(failure(FailureClass.INVALID_CONTENT_TYPE, "provider did not return application/json", attempt=attempt))
                    try:
                        return parse_provider_response(response_body, advertised_tools=request.tools, limits=limits)
                    except ProviderError as error:
                        raise ProviderError(error.failure) from None
            except ProviderError as error:
                last = error.failure
            except socket.timeout:
                classification = FailureClass.TOTAL_REQUEST_TIMEOUT if self.clock() >= deadline_at else FailureClass.READ_TIMEOUT
                last = failure(classification, "provider read inactivity deadline expired", attempt=attempt)
            except TimeoutError:
                last = failure(FailureClass.CONNECT_TIMEOUT, "provider connect deadline expired", attempt=attempt)
            except OSError:
                last = failure(FailureClass.DNS_OR_CONNECTION_FAILURE, "provider connection failed", attempt=attempt)
            if last is None:
                last = failure(FailureClass.PERMANENT_PROVIDER_FAILURE, "provider attempt failed", attempt=attempt)
            remaining_ms = max(0, int((deadline_at - self.clock()) * 1_000))
            decision = decide_retry(last, completed_attempts=attempt, remaining_ms=remaining_ms, limits=limits)
            if not decision.eligible:
                if last.retryable and attempt >= limits.provider_attempt_count and limits.provider_attempt_count > 1:
                    raise ProviderError(failure(FailureClass.RETRY_EXHAUSTED, last.classification.value, attempt=attempt))
                raise ProviderError(last)
            if decision.delay_ms:
                if decision.delay_ms / 1_000.0 > deadline_at - self.clock():
                    raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "retry delay exceeds total deadline", attempt=attempt))
                self.sleep(decision.delay_ms / 1_000.0)
        raise ProviderError(failure(FailureClass.RETRY_EXHAUSTED, "provider attempt budget exhausted", attempt=limits.provider_attempt_count))

    def _one_attempt(self, endpoint: ValidatedEndpoint, body: bytes, limits: Limits, deadline: float) -> tuple[bytes, str | None, int, int | None]:
        remaining = deadline - self.clock()
        connection = http.client.HTTPConnection(endpoint.connect_host, endpoint.port, timeout=min(remaining, limits.provider_connect_timeout_ms / 1_000.0))
        try:
            try:
                connection.connect()
            except socket.timeout:
                raise ProviderError(failure(FailureClass.CONNECT_TIMEOUT, "provider connect deadline expired")) from None
            connection.request(
                "POST", endpoint.path, body=body,
                headers={"Accept": "application/json", "Content-Type": "application/json", "Content-Length": str(len(body))},
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type")
            retry_after = _retry_after(response.getheader("Retry-After"), limits)
            if response.status in {301, 302, 303, 307, 308}:
                # Read no remote body and never expose the Location value.
                return b"", content_type, response.status, retry_after
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except ValueError:
                    raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "provider length is malformed")) from None
                if declared_size < 0 or declared_size > limits.provider_response_bytes:
                    raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "provider response exceeds byte limit"))
            chunks = bytearray()
            while True:
                remaining_now = min(deadline - self.clock(), limits.provider_read_inactivity_timeout_ms / 1_000.0)
                if remaining_now <= 0:
                    raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider total deadline expired"))
                connection.sock.settimeout(remaining_now) if connection.sock is not None else None
                try:
                    chunk = response.read(min(8_192, limits.provider_response_bytes - len(chunks) + 1))
                except http.client.IncompleteRead:
                    raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "provider response ended early")) from None
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > limits.provider_response_bytes:
                    raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "provider response exceeds byte limit"))
            if declared is not None and len(chunks) != declared_size:
                raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "provider response ended before declared length"))
            return bytes(chunks), content_type, response.status, retry_after
        finally:
            connection.close()


def _retry_after(value: str | None, limits: Limits) -> int | None:
    if value is None:
        return None
    if not value.isascii() or not value.isdigit() or len(value) > 4:
        return None
    seconds = int(value)
    milliseconds = seconds * 1_000
    if milliseconds > limits.retry_after_ms:
        return None
    return milliseconds
