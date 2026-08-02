"""Pure retry eligibility and bounded delay decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ClassifiedFailure
from .limits import Limits


@dataclass(frozen=True)
class RetryDecision:
    eligible: bool
    delay_ms: int = 0
    reason: str = ""


def decide_retry(
    classified: ClassifiedFailure,
    *,
    completed_attempts: int,
    remaining_ms: int,
    limits: Limits,
) -> RetryDecision:
    if not classified.retryable:
        return RetryDecision(False, 0, "failure is non-retryable")
    if completed_attempts >= limits.provider_attempt_count:
        return RetryDecision(False, 0, "attempt budget exhausted")
    if remaining_ms <= 0:
        return RetryDecision(False, 0, "total deadline exhausted")
    requested = classified.retry_after_ms if classified.retry_after_ms is not None else limits.retry_backoff_ms
    delay = min(max(0, requested), limits.retry_after_ms, limits.retry_backoff_ms if classified.retry_after_ms is None else limits.retry_after_ms)
    if delay > remaining_ms:
        return RetryDecision(False, 0, "retry delay exceeds remaining deadline")
    return RetryDecision(True, delay, "bounded transport retry permitted")
