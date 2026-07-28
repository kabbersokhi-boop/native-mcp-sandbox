"""Bounded transcript events with a closed, canonical schema."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence

from .contracts import EvidenceProvenance, RequestCorrelationId, ToolCallId
from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, Limits
from .redaction import redact_json


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
        if not self.event or len(self.event) > 64 or not isinstance(self.adapter, str) or len(self.adapter) > 64:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript identity is invalid"))
        if not isinstance(self.correlation_id, RequestCorrelationId) or not isinstance(self.provenance, EvidenceProvenance):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript identity is not project-owned"))
        if len(self.proposal_ids) > DEFAULT_LIMITS.proposed_tool_call_count or len(set(self.proposal_ids)) != len(self.proposal_ids):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal IDs are invalid"))
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or not 0 <= self.byte_count <= 512 * 1024:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript byte count is invalid"))
        for key, value in self.metadata.items():
            if not isinstance(key, str) or not isinstance(value, str) or len(key) > 64 or len(value.encode("utf-8", "replace")) > 256:
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata is invalid"))

    def to_json_bytes(self, limits: Limits = DEFAULT_LIMITS) -> bytes:
        value: dict[str, Any] = {
            "schemaVersion": 1,
            "event": self.event,
            "adapter": self.adapter,
            "model": self.model,
            "correlationId": str(self.correlation_id),
            "provenance": self.provenance.value,
            "proposalIds": [str(item) for item in self.proposal_ids],
            "byteCount": self.byte_count,
            "metadata": redact_json(dict(self.metadata)),
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
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw, object_pairs_hook=_reject_duplicates)
    except DuplicateKey:
        raise ProviderError(failure(FailureClass.DUPLICATE_KEY_JSON, "duplicate transcript key")) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError(failure(FailureClass.MALFORMED_JSON, "transcript JSON is malformed")) from None
    if not isinstance(value, dict):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript must be an object"))
    allowed = {"schemaVersion", "event", "adapter", "model", "correlationId", "provenance", "proposalIds", "byteCount", "metadata", "failureClass", "retryEligible"}
    required = {"schemaVersion", "event", "adapter", "model", "correlationId", "provenance", "proposalIds", "byteCount", "metadata"}
    if set(value) - allowed or required - set(value) or value["schemaVersion"] != 1:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript schema is not closed"))
    try:
        proposals = tuple(ToolCallId(item) for item in value["proposalIds"])
        return TranscriptEvent(
            value["event"], value["adapter"], value["model"], RequestCorrelationId(value["correlationId"]),
            EvidenceProvenance(value["provenance"]), proposals,
            FailureClass(value["failureClass"]) if "failureClass" in value else None,
            value.get("retryEligible"), value["byteCount"], value["metadata"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, str(error)[:128])) from None


class DuplicateKey(Exception):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, item in pairs:
        if key in output:
            raise DuplicateKey(key)
        output[key] = item
    return output
