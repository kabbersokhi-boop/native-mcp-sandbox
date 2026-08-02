"""Bounded non-streaming transport for the deterministic loopback fake only."""

from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import re
import socket
import time
from typing import Callable, Protocol

from .contracts import ProviderFinalMessage, ProviderRequest, ProviderToolCallProposal, parse_provider_response
from .endpoint_policy import ValidatedEndpoint, redirect_rejection, validate_loopback_transport_endpoint
from .errors import ClassifiedFailure, FailureClass, ProviderError, failure, http_failure
from .limits import DEFAULT_LIMITS, Limits
from .retry import decide_retry


ProviderResponse = ProviderFinalMessage | tuple[ProviderToolCallProposal, ...]
ConnectionFactory = Callable[[str, int, float], http.client.HTTPConnection]


def _http_connection(host: str, port: int, timeout: float) -> http.client.HTTPConnection:
    return http.client.HTTPConnection(host, port, timeout=timeout)


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
    connection_factory: ConnectionFactory = field(default=_http_connection, repr=False)

    def send(
        self,
        endpoint: ValidatedEndpoint,
        request: ProviderRequest,
        *,
        limits: Limits = DEFAULT_LIMITS,
        correlation_id: str,
        deadline: float | None = None,
    ) -> ProviderResponse:
        # This is the authority boundary.  It runs on every send, including
        # callers that manually constructed a ValidatedEndpoint.
        validate_loopback_transport_endpoint(endpoint)
        if not isinstance(correlation_id, str) or str(request.correlation_id) != correlation_id:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transport correlation ID mismatch"))
        try:
            body = request.to_json_bytes(limits)
        except ProviderError:
            raise
        except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "provider request is invalid")) from None

        now = self.clock()
        deadline_at = now + limits.provider_total_timeout_ms / 1_000.0
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not deadline > now:
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline is invalid or expired"))
            deadline_at = min(deadline_at, float(deadline))
        last: ClassifiedFailure | None = None
        for attempt in range(1, limits.provider_attempt_count + 1):
            if deadline_at - self.clock() <= 0:
                raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider total deadline expired", attempt=attempt - 1))
            last = None
            try:
                response_body, content_type, status, retry_after = self._one_attempt(endpoint, body, limits, deadline_at)
                if 300 <= status <= 399:
                    last = redirect_rejection(None)
                elif status < 200 or status >= 300:
                    last = http_failure(status, retry_after_ms=retry_after)
                else:
                    if content_type is None or content_type.lower().split(";", 1)[0].strip() != "application/json":
                        raise ProviderError(failure(FailureClass.INVALID_CONTENT_TYPE, "provider did not return application/json", attempt=attempt))
                    return parse_provider_response(response_body, advertised_tools=request.tools, limits=limits)
            except ProviderError as error:
                last = error.failure
            except socket.timeout:
                classification = FailureClass.TOTAL_REQUEST_TIMEOUT if self.clock() >= deadline_at else FailureClass.READ_TIMEOUT
                last = failure(classification, "provider read inactivity deadline expired", attempt=attempt)
            except TimeoutError:
                last = failure(FailureClass.CONNECT_TIMEOUT, "provider connect deadline expired", attempt=attempt)
            except (OSError, http.client.HTTPException):
                last = failure(FailureClass.DNS_OR_CONNECTION_FAILURE, "provider connection failed", attempt=attempt)
            except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
                last = failure(FailureClass.MALFORMED_HTTP_RESPONSE, "provider HTTP response is malformed", attempt=attempt)
            if last is None:
                last = failure(FailureClass.PERMANENT_PROVIDER_FAILURE, "provider attempt failed", attempt=attempt)
            remaining_ms = max(0, int((deadline_at - self.clock()) * 1_000))
            decision = decide_retry(last, completed_attempts=attempt, remaining_ms=remaining_ms, limits=limits)
            if not decision.eligible:
                if last.retryable and attempt >= limits.provider_attempt_count and limits.provider_attempt_count > 1:
                    raise ProviderError(failure(FailureClass.RETRY_EXHAUSTED, "provider retry budget exhausted", attempt=attempt))
                raise ProviderError(last)
            if decision.delay_ms:
                if decision.delay_ms / 1_000.0 > deadline_at - self.clock():
                    raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "retry delay exceeds total deadline", attempt=attempt))
                self.sleep(decision.delay_ms / 1_000.0)
        raise ProviderError(failure(FailureClass.RETRY_EXHAUSTED, "provider retry budget exhausted", attempt=limits.provider_attempt_count))

    def _one_attempt(self, endpoint: ValidatedEndpoint, body: bytes, limits: Limits, deadline: float) -> tuple[bytes, str | None, int, int | None]:
        remaining = deadline - self.clock()
        timeout = min(remaining, limits.provider_connect_timeout_ms / 1_000.0)
        if timeout <= 0:
            raise ProviderError(failure(FailureClass.CONNECT_TIMEOUT, "provider connect deadline expired"))
        connection = self.connection_factory(endpoint.connect_host, endpoint.port, timeout)
        try:
            try:
                connection.connect()
            except (socket.timeout, TimeoutError):
                raise ProviderError(failure(FailureClass.CONNECT_TIMEOUT, "provider connect deadline expired")) from None
            connection.request(
                "POST", endpoint.path, body=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            self._set_read_timeout(connection, deadline, limits)
            response = connection.getresponse()
            status = response.status
            if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                raise ProviderError(failure(FailureClass.MALFORMED_HTTP_RESPONSE, "provider HTTP status is malformed"))
            content_type = response.getheader("Content-Type")
            retry_after = _retry_after(response.getheader("Retry-After"), limits)
            if 300 <= status <= 399:
                # Do not read or log a redirect body or Location header.
                return b"", content_type, status, retry_after
            declared = response.getheader("Content-Length")
            declared_size: int | None = None
            if declared is not None:
                if not isinstance(declared, str) or not re.fullmatch(r"[0-9]+", declared):
                    raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "provider length is malformed"))
                declared_size = int(declared)
                if declared_size < 0 or declared_size > limits.provider_response_bytes:
                    raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "provider response exceeds byte limit"))
            chunks = bytearray()
            while True:
                self._set_read_timeout(connection, deadline, limits)
                try:
                    chunk = response.read(min(8_192, limits.provider_response_bytes - len(chunks) + 1))
                except http.client.IncompleteRead:
                    raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "provider response ended early")) from None
                if not isinstance(chunk, bytes):
                    raise ProviderError(failure(FailureClass.MALFORMED_HTTP_RESPONSE, "provider response body is malformed"))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > limits.provider_response_bytes:
                    raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "provider response exceeds byte limit"))
            if declared_size is not None and len(chunks) != declared_size:
                raise ProviderError(failure(FailureClass.TRUNCATED_RESPONSE, "provider response ended before declared length"))
            return bytes(chunks), content_type, status, retry_after
        finally:
            try:
                connection.close()
            except (AttributeError, OSError, TypeError, ValueError):
                pass

    def _set_read_timeout(self, connection: http.client.HTTPConnection, deadline: float, limits: Limits) -> None:
        remaining = min(deadline - self.clock(), limits.provider_read_inactivity_timeout_ms / 1_000.0)
        if remaining <= 0:
            raise ProviderError(failure(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider total deadline expired"))
        sock = getattr(connection, "sock", None)
        if sock is not None:
            sock.settimeout(remaining)


_RETRY_AFTER = re.compile(r"^[0-9]+(?:\.[0-9]{1,3})?$")


def _retry_after(value: str | None, limits: Limits) -> int | None:
    # Keep parsing bounded before converting untrusted header text to an int.
    if value is None or not isinstance(value, str) or not value.isascii() or len(value) > 16 or not _RETRY_AFTER.fullmatch(value):
        return None
    whole, separator, fraction = value.partition(".")
    try:
        milliseconds = int(whole) * 1_000
        if separator:
            milliseconds += int(fraction.ljust(3, "0"))
    except (TypeError, ValueError, OverflowError):
        return None
    if milliseconds > limits.retry_after_ms:
        return None
    return milliseconds
