"""Project-owned bounded failure taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class FailureClass(str, Enum):
    INVALID_PROVIDER_CONFIGURATION = "invalid_provider_configuration"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"
    ENDPOINT_POLICY_REJECTION = "endpoint_policy_rejection"
    INSECURE_SCHEME = "insecure_scheme"
    TLS_VERIFICATION_FAILURE = "tls_verification_failure"
    REDIRECT_REJECTED = "redirect_rejected"
    DNS_OR_CONNECTION_FAILURE = "dns_or_connection_failure"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    TOTAL_REQUEST_TIMEOUT = "total_request_timeout"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    REQUEST_TOO_LARGE = "request_too_large_before_transmission"
    HTTP_400_INVALID_REQUEST = "http_400_invalid_request"
    HTTP_401_AUTHENTICATION_FAILURE = "http_401_authentication_failure"
    HTTP_403_AUTHORIZATION_FAILURE = "http_403_authorization_failure"
    HTTP_404_ENDPOINT_OR_MODEL_NOT_FOUND = "http_404_endpoint_or_model_not_found"
    HTTP_408_REQUEST_TIMEOUT = "http_408_request_timeout"
    HTTP_413_PAYLOAD_TOO_LARGE = "http_413_payload_too_large"
    HTTP_422_SEMANTIC_REJECTION = "http_422_semantic_request_rejection"
    OTHER_PERMANENT_4XX = "other_permanent_4xx"
    HTTP_429_RATE_LIMITED = "http_429_rate_limited"
    TRANSIENT_5XX = "transient_5xx_provider_failure"
    PERMANENT_PROVIDER_FAILURE = "permanent_provider_failure"
    MALFORMED_JSON = "malformed_json"
    DUPLICATE_KEY_JSON = "duplicate_key_json"
    TRUNCATED_RESPONSE = "truncated_response"
    OVERSIZED_RESPONSE = "oversized_response"
    UNSUPPORTED_PROVIDER_CONTENT = "unsupported_provider_content"
    INVALID_TOOL_PROPOSAL = "invalid_tool_proposal"
    REPLAY_OR_DUPLICATE_PROPOSAL = "replay_or_duplicate_proposal"
    RETRY_EXHAUSTED = "retry_exhausted"
    CANCELLED = "cancelled"
    LOCAL_VALIDATION_FAILURE = "local_validation_failure"
    LOCAL_AUTHORIZATION_FAILURE = "local_authorization_failure"
    LOCAL_POLICY_FAILURE = "local_policy_failure"


@dataclass(frozen=True)
class ClassifiedFailure:
    classification: FailureClass
    detail: str = ""
    status_code: int | None = None
    retry_after_ms: int | None = None
    attempt: int | None = None

    def __post_init__(self) -> None:
        if len(self.detail.encode("utf-8", "replace")) > 256:
            object.__setattr__(self, "detail", self.detail.encode("utf-8", "replace")[:256].decode("utf-8", "ignore"))
        if self.status_code is not None and (self.status_code < 100 or self.status_code > 599):
            raise ValueError("status_code is not a valid HTTP status")
        if self.retry_after_ms is not None and not 0 <= self.retry_after_ms <= 5_000:
            raise ValueError("retry_after_ms is outside the bounded diagnostic range")
        if self.attempt is not None and not 0 <= self.attempt <= 5:
            raise ValueError("attempt is outside the bounded diagnostic range")

    @property
    def retryable(self) -> bool:
        return self.classification in {
            FailureClass.HTTP_408_REQUEST_TIMEOUT,
            FailureClass.HTTP_429_RATE_LIMITED,
            FailureClass.DNS_OR_CONNECTION_FAILURE,
            FailureClass.CONNECT_TIMEOUT,
            FailureClass.TRANSIENT_5XX,
        }

    def safe_text(self) -> str:
        pieces = [self.classification.value]
        if self.status_code is not None:
            pieces.append(f"status={self.status_code}")
        if self.attempt is not None:
            pieces.append(f"attempt={self.attempt}")
        if self.detail:
            pieces.append(self.detail)
        return ": ".join(pieces)


class ProviderError(Exception):
    """Exception carrying only a project-owned classified failure."""

    def __init__(self, classified: ClassifiedFailure):
        self.failure = classified
        super().__init__(classified.safe_text())


def failure(
    classification: FailureClass,
    detail: str = "",
    *,
    status_code: int | None = None,
    retry_after_ms: int | None = None,
    attempt: int | None = None,
) -> ClassifiedFailure:
    return ClassifiedFailure(classification, detail, status_code, retry_after_ms, attempt)


def http_failure(status: int, *, retry_after_ms: int | None = None) -> ClassifiedFailure:
    mapping = {
        400: FailureClass.HTTP_400_INVALID_REQUEST,
        401: FailureClass.HTTP_401_AUTHENTICATION_FAILURE,
        403: FailureClass.HTTP_403_AUTHORIZATION_FAILURE,
        404: FailureClass.HTTP_404_ENDPOINT_OR_MODEL_NOT_FOUND,
        408: FailureClass.HTTP_408_REQUEST_TIMEOUT,
        413: FailureClass.HTTP_413_PAYLOAD_TOO_LARGE,
        422: FailureClass.HTTP_422_SEMANTIC_REJECTION,
        429: FailureClass.HTTP_429_RATE_LIMITED,
    }
    classification = mapping.get(status)
    if classification is None:
        classification = FailureClass.TRANSIENT_5XX if 500 <= status <= 599 else FailureClass.OTHER_PERMANENT_4XX
    return failure(classification, f"HTTP status {status}", status_code=status, retry_after_ms=retry_after_ms)
