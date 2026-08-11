"""Bounded canonical transcript events with safe control-plane identities."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import json
from typing import Any, Mapping

from .contracts import EvidenceProvenance, ModelIdentifier, RequestCorrelationId, ToolCallId, _FrozenDict, parse_closed_json
from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, HARD_LIMITS, Limits
from .redaction import redact_json


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAFE_METADATA_KEYS = {"mode", "phase", "source", "reason", "status", "retry", "category", "provider", "operation"}
_SUSPICIOUS = ("authorization", "proxy-authorization", "bearer", "api-key", "api-", "apikey", "sk-", "password", "secret", "token")
_PHASE10_EVENTS = {"process_start", "initialize_request", "initialize_response", "initialized_notification", "tools_list_request", "tools_list_response", "surface_captured", "surface_revalidated", "provider_turn_start", "provider_turn_response", "proposal_rejected", "proposal_duplicate", "authorized", "mcp_request", "mcp_response", "evidence_validated", "skipped", "deadline", "cancelled", "failure", "shutdown_start", "shutdown_terminate", "shutdown_kill", "shutdown_complete", "shutdown_unreaped", "outcome", "transcript_limit", "surface", "provider_turn", "failed"}
_PHASE10_KEYS = {"surface", "turn", "bytes", "action", "proposal", "response", "failure", "outcome"}
_PHASE10_SCHEMA = {
    "process_start": set(), "initialize_request": set(), "initialize_response": {"response"},
    "initialized_notification": set(), "tools_list_request": set(), "tools_list_response": {"response"},
    "surface_captured": {"surface"}, "surface_revalidated": {"surface"},
    "provider_turn_start": {"turn", "bytes"}, "provider_turn_response": {"turn", "bytes"},
    "proposal_rejected": {"proposal"}, "proposal_duplicate": {"proposal"},
    "authorized": {"action", "proposal"}, "mcp_request": {"action", "response"},
    "mcp_response": {"action", "response"}, "evidence_validated": {"action", "response"},
    "skipped": {"proposal"}, "deadline": set(), "cancelled": set(), "failure": {"failure"},
    "shutdown_start": set(), "shutdown_terminate": set(), "shutdown_kill": set(), "shutdown_complete": set(), "shutdown_unreaped": set(),
    "outcome": {"outcome"}, "transcript_limit": set(),
    # Compatibility aliases emitted by the initial Phase 10.2 correction.
    "surface": {"surface"}, "provider_turn": {"turn", "bytes"}, "failed": {"failure", "action"},
}


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


def _metadata(value: Any, *, limit: int) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or len(value) > limit:
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
    frozen = _FrozenDict()
    for key, item in result.items():
        dict.__setitem__(frozen, key, item)
    return frozen


@dataclass(frozen=True)
class TranscriptEvent:
    event: str
    adapter: str
    model: ModelIdentifier | str
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
        try:
            model = self.model if isinstance(self.model, ModelIdentifier) else ModelIdentifier(self.model)
        except ProviderError as error:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript model is invalid")) from error
        object.__setattr__(self, "model", model)
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
        object.__setattr__(self, "metadata", _metadata(self.metadata, limit=HARD_LIMITS.object_array_items))

    def to_json_bytes(self, limits: Limits = DEFAULT_LIMITS) -> bytes:
        _safe_identity(self.event, "event")
        _safe_identity(self.adapter, "adapter")
        model = ModelIdentifier(self.model)
        if not isinstance(self.correlation_id, RequestCorrelationId):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript correlation ID is invalid"))
        RequestCorrelationId(str(self.correlation_id))
        if not isinstance(self.provenance, EvidenceProvenance):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript provenance is invalid"))
        if not isinstance(self.proposal_ids, tuple):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal IDs are invalid"))
        for item in self.proposal_ids:
            if not isinstance(item, ToolCallId):
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal IDs are invalid"))
            ToolCallId.require_canonical(str(item))
        if self.failure_class is not None and not isinstance(self.failure_class, FailureClass):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript failure class is invalid"))
        if self.retry_eligible is not None and not isinstance(self.retry_eligible, bool):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript retry flag is invalid"))
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or not 0 <= self.byte_count <= 512 * 1024:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript byte count is invalid"))
        if len(self.proposal_ids) > limits.proposed_tool_call_count:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal count exceeds configured limit"))
        metadata = _metadata(self.metadata, limit=limits.object_array_items)
        if any(len(value.encode("utf-8")) > limits.message_bytes for value in metadata.values()):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "transcript metadata exceeds configured limit"))
        value: dict[str, Any] = {
            "schemaVersion": 1,
            "event": self.event,
            "adapter": self.adapter,
            "model": str(model),
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
        proposals = tuple(ToolCallId.require_canonical(item) for item in value["proposalIds"])
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


class Phase10Transcript:
    """Incrementally bounded, closed Phase 10.2 control transcript."""
    def __init__(self, limits: Limits = DEFAULT_LIMITS) -> None:
        self._limits, self._events, self._limited = limits, [], False
        self._terminal = {"event": "transcript_limit", "metadata": {}}

    def add(self, event: str, **metadata: str) -> None:
        if self._limited:
            return
        if event not in _PHASE10_EVENTS or (set(metadata) != _PHASE10_SCHEMA[event] and not (event == "failed" and set(metadata) == {"failure"})):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "Phase 10 transcript event is invalid"))
        values: dict[str, str] = {}
        for key, value in metadata.items():
            if not isinstance(value, str) or not value or len(value.encode("ascii", "ignore")) != len(value) or len(value) > 64:
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "Phase 10 transcript metadata is invalid"))
            if any(part in value.lower() for part in _SUSPICIOUS) or value.startswith("/") or "\\" in value:
                values[key] = "redacted"
            else:
                values[key] = value
        candidate = self._events + [{"event": event, "metadata": values}]
        # Reserve terminal-event space before accepting ordinary control data.
        if event == "transcript_limit" or len(_phase10_bytes(candidate + [self._terminal], True)) <= self._limits.transcript_bytes:
            self._events = candidate
            return
        terminal = self._events + [self._terminal]
        if len(_phase10_bytes(terminal, True)) > self._limits.transcript_bytes:
            raise ProviderError(failure(FailureClass.OVERSIZED_RESPONSE, "transcript terminal cannot fit"))
        self._events = terminal
        self._limited = True

    def to_json_bytes(self) -> bytes:
        return _phase10_bytes(self._events, self._limited)


def _phase10_bytes(events: list[dict[str, Any]], limited: bool) -> bytes:
    return json.dumps({"schemaVersion":2, "events":events, "limited":limited}, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_phase_10_2_transcript(raw: bytes | str, limits: Limits = DEFAULT_LIMITS) -> tuple[Mapping[str, Any], ...]:
    value = parse_closed_json(raw, limits, byte_limit=limits.transcript_bytes)
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "events", "limited"} or value["schemaVersion"] != 2 or type(value["limited"]) is not bool or not isinstance(value["events"], list):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "Phase 10 transcript is not closed"))
    result=[]
    for item in value["events"]:
        if not isinstance(item, dict) or set(item) != {"event", "metadata"} or item["event"] not in _PHASE10_EVENTS or not isinstance(item["metadata"], dict) or (set(item["metadata"]) != _PHASE10_SCHEMA[item["event"]] and not (item["event"] == "failed" and set(item["metadata"]) == {"failure"})):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "Phase 10 transcript event is invalid"))
        if any(not isinstance(v, str) or len(v) > 64 for v in item["metadata"].values()):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "Phase 10 transcript metadata is invalid"))
        result.append(_FrozenDict(item))
    return tuple(result)
