"""Bounded canonical transcript events with safe control-plane identities."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import json
from typing import Any, Mapping

from .contracts import EvidenceProvenance, RequestCorrelationId, ToolCallId, parse_closed_json
from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, HARD_LIMITS, Limits
from .redaction import redact_json


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAFE_METADATA_KEYS = {"mode", "phase", "source", "reason", "status", "retry", "category", "provider", "operation"}
_SUSPICIOUS = ("authorization", "proxy-authorization", "bearer", "api-key", "api-", "apikey", "sk-", "password", "secret", "token")


def _safe_identity(value: Any, label: str) -> str:
    try:
        size = len(value.encode("utf-8")) if isinstance(value, str) else -1
    except UnicodeEncodeError:
        size = -1
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value) or size < 1 or size > 64:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"transcript {label} is invalid"))
    lowered = value.lower()
    if any(marker in lowered for marker in _SUSPICIOUS) or value.isdigit():
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"transcript {label} is invalid"))
    return value


def _metadata(value: Any, *, limit: int) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > limit:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata is invalid"))
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in _SAFE_METADATA_KEYS or not isinstance(item, str):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata is invalid"))
        try:
            size = len(item.encode("utf-8"))
        except UnicodeEncodeError:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata is invalid")) from None
        if not item or size > HARD_LIMITS.message_bytes or any(ord(char) < 0x20 or ord(char) == 0x7f for char in item):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata is invalid"))
        lowered = item.lower()
        if any(marker in lowered for marker in _SUSPICIOUS) or item.startswith("/") or any(char.isspace() for char in item):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata is invalid"))
        result[key] = item
    return result


@dataclass(frozen=True)
class TranscriptEvent:
    event: str
    adapter: str
    model: str
    correlation_id: RequestCorrelationId
    provenance: EvidenceProvenance
    proposal_ids: tuple[ToolCallId, ...] = ()
    failure_class: FailureClass | None = None
    retry_eligible: bool | None = None
    byte_count: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _safe_identity(self.event, "event")
        _safe_identity(self.adapter, "adapter")
        _safe_identity(self.model, "model")
        if not isinstance(self.correlation_id, RequestCorrelationId) or not isinstance(self.provenance, EvidenceProvenance):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript identity is not project-owned"))
        if not isinstance(self.proposal_ids, tuple) or len(self.proposal_ids) > HARD_LIMITS.proposed_tool_call_count or any(not isinstance(item, ToolCallId) for item in self.proposal_ids) or len(set(self.proposal_ids)) != len(self.proposal_ids):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal IDs are invalid"))
        if self.failure_class is not None and not isinstance(self.failure_class, FailureClass):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript failure class is invalid"))
        if self.retry_eligible is not None and not isinstance(self.retry_eligible, bool):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript retry flag is invalid"))
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or not 0 <= self.byte_count <= 512 * 1024:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript byte count is invalid"))
        _metadata(self.metadata, limit=HARD_LIMITS.object_array_items)

    def to_json_bytes(self, limits: Limits = DEFAULT_LIMITS) -> bytes:
        if len(self.proposal_ids) > limits.proposed_tool_call_count:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal count exceeds configured limit"))
        metadata = _metadata(self.metadata, limit=limits.object_array_items)
        if any(len(value.encode("utf-8")) > limits.message_bytes for value in metadata.values()):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata exceeds configured limit"))
        value: dict[str, Any] = {
            "schemaVersion": 1,
            "event": self.event,
            "adapter": self.adapter,
            "model": self.model,
            "correlationId": str(self.correlation_id),
            "provenance": self.provenance.value,
            "proposalIds": [str(item) for item in self.proposal_ids],
            "byteCount": self.byte_count,
            "metadata": redact_json(metadata),
        }
        if self.failure_class is not None:
            value["failureClass"] = self.failure_class.value
        if self.retry_eligible is not None:
            value["retryEligible"] = self.retry_eligible
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > limits.transcript_bytes:
            raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "transcript exceeds byte limit"))
        return encoded


def parse_transcript(raw: bytes | str, limits: Limits = DEFAULT_LIMITS) -> TranscriptEvent:
    # Check the encoded byte length before json.loads.  This is the allocation
    # boundary for transcript input, not an after-the-fact serialization check.
    if not isinstance(raw, (bytes, str)):
        raise ProviderError(failure(FailureClass.MALFORMED_JSON, "transcript input type is invalid"))
    try:
        encoded = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    except UnicodeEncodeError:
        raise ProviderError(failure(FailureClass.MALFORMED_JSON, "transcript input is not valid UTF-8")) from None
    if len(encoded) > limits.transcript_bytes:
        raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "transcript exceeds byte limit"))
    try:
        value = parse_closed_json(encoded, limits, byte_limit=limits.transcript_bytes)
        if not isinstance(value, dict):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript must be an object"))
        allowed = {"schemaVersion", "event", "adapter", "model", "correlationId", "provenance", "proposalIds", "byteCount", "metadata", "failureClass", "retryEligible"}
        required = {"schemaVersion", "event", "adapter", "model", "correlationId", "provenance", "proposalIds", "byteCount", "metadata"}
        if set(value) - allowed or required - set(value) or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript schema is not closed"))
        if not isinstance(value["proposalIds"], list) or len(value["proposalIds"]) > limits.proposed_tool_call_count:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal count is invalid"))
        if not isinstance(value["byteCount"], int) or isinstance(value["byteCount"], bool) or value["byteCount"] < 0:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript byte count is invalid"))
        metadata = _metadata(value["metadata"], limit=limits.object_array_items)
        proposals = tuple(ToolCallId(item) for item in value["proposalIds"])
        failure_class = None if "failureClass" not in value else FailureClass(value["failureClass"])
        retry_eligible = value.get("retryEligible")
        return TranscriptEvent(
            value["event"], value["adapter"], value["model"], RequestCorrelationId(value["correlationId"]),
            EvidenceProvenance(value["provenance"]), proposals, failure_class,
            retry_eligible, value["byteCount"], metadata,
        )
    except ProviderError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript fields are malformed")) from None
