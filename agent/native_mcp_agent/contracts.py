"""Provider-neutral closed contracts and bounded JSON parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, Limits
from .retry import RetryDecision


class ContractError(ProviderError):
    pass


class RequestCorrelationId(str):
    def __new__(cls, value: str) -> "RequestCorrelationId":
        _identifier(value, "request correlation ID", FailureClass.LOCAL_VALIDATION_FAILURE)
        return str.__new__(cls, value)


class ToolCallId(str):
    def __new__(cls, value: str) -> "ToolCallId":
        _identifier(value, "tool call ID", FailureClass.INVALID_TOOL_PROPOSAL)
        return str.__new__(cls, value)


class EvidenceProvenance(str, Enum):
    PROVIDER_SUGGESTION = "provider_suggestion"
    ACCEPTED_TOOL_PROPOSAL = "accepted_tool_proposal"
    REJECTED_TOOL_PROPOSAL = "rejected_tool_proposal"
    VALIDATED_MCP_EVIDENCE = "validated_mcp_evidence"
    LOCALLY_DERIVED_PREDICATE = "locally_derived_predicate"
    COMMITTED_SYNTHETIC_FIXTURE_ASSERTION = "committed_synthetic_fixture_assertion"
    LOCAL_CONTROL_EVENT = "local_control_event"
    FINAL_SUPPORTED_CONCLUSION = "final_supported_conclusion"
    UNSUPPORTED_PROVIDER_OUTPUT = "unsupported_provider_output"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


def _identifier(value: Any, label: str, classification: FailureClass) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8", "replace")) > 256:
        raise ContractError(failure(classification, f"{label} must be a bounded non-empty string"))


def _bounded_text(value: Any, label: str, maximum: int, classification: FailureClass = FailureClass.LOCAL_VALIDATION_FAILURE) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8", "replace")) > maximum:
        raise ContractError(failure(classification, f"{label} is empty, incorrectly typed, or oversized"))
    return value


def _json_value(value: Any, *, depth: int = 0, limits: Limits = DEFAULT_LIMITS) -> None:
    if depth > limits.json_nesting_depth:
        raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON nesting depth exceeded"))
    if isinstance(value, dict):
        if len(value) > limits.object_array_items:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON object item limit exceeded"))
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON object key is invalid"))
            _json_value(child, depth=depth + 1, limits=limits)
    elif isinstance(value, list):
        if len(value) > limits.object_array_items:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON array item limit exceeded"))
        for child in value:
            _json_value(child, depth=depth + 1, limits=limits)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "non-finite JSON number"))
    else:
        raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "unsupported JSON value"))


def _pairs_reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(failure(FailureClass.DUPLICATE_KEY_JSON, f"duplicate key {key!r}"))
        result[key] = value
    return result


def parse_closed_json(raw: bytes | str, limits: Limits = DEFAULT_LIMITS) -> Any:
    encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    if not isinstance(encoded, bytes):
        raise ContractError(failure(FailureClass.MALFORMED_JSON, "JSON input is not bytes or text"))
    if len(encoded) > limits.provider_response_bytes:
        raise ContractError(failure(FailureClass.OVERSIZED_RESPONSE, "JSON input exceeds response limit"))
    try:
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_pairs_reject_duplicates)
    except ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        detail = str(error).encode("utf-8", "replace")[:128].decode("utf-8", "ignore")
        raise ContractError(failure(FailureClass.MALFORMED_JSON, detail)) from None
    _json_value(value, limits=limits)
    return value


def _closed_object(value: Any, allowed: set[str], required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} must be an object"))
    unknown = set(value) - allowed
    if unknown:
        raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} contains unknown fields"))
    missing = required - set(value)
    if missing:
        raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} is missing required fields"))
    return value


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str
    model: str
    verify_tls: bool = True
    allow_loopback_http: bool = False
    redirects: str = "reject"

    def __post_init__(self) -> None:
        _bounded_text(self.endpoint, "provider endpoint", 2_048, FailureClass.INVALID_PROVIDER_CONFIGURATION)
        _bounded_text(self.model, "model identifier", 256, FailureClass.INVALID_PROVIDER_CONFIGURATION)
        if not isinstance(self.verify_tls, bool) or not isinstance(self.allow_loopback_http, bool):
            raise ContractError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "TLS and loopback options must be boolean"))
        if self.redirects != "reject":
            raise ContractError(failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "redirect mode is not supported"))


@dataclass(frozen=True)
class ProviderMessage:
    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, MessageRole):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "message role is invalid"))
        _bounded_text(self.content, "message content", DEFAULT_LIMITS.message_bytes)


@dataclass(frozen=True)
class GenerationControls:
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.temperature, "temperature"), (self.top_p, "top_p")):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.0 <= value <= 2.0):
                raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} is invalid"))
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int) or not 0 <= self.seed <= 2**31 - 1):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "seed is invalid"))


@dataclass(frozen=True)
class AdvertisedTool:
    name: str
    parameters: Mapping[str, Any]
    description: str = ""

    def __post_init__(self) -> None:
        _identifier(self.name, "tool name", FailureClass.LOCAL_VALIDATION_FAILURE)
        if not isinstance(self.parameters, dict):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "tool parameters must be an object"))
        _json_value(dict(self.parameters))
        if self.description and len(self.description.encode("utf-8", "replace")) > 1_024:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "tool description is oversized"))


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    messages: tuple[ProviderMessage, ...]
    tools: tuple[AdvertisedTool, ...]
    max_output_tokens: int
    correlation_id: RequestCorrelationId
    generation: GenerationControls = field(default_factory=GenerationControls)

    def __post_init__(self) -> None:
        _bounded_text(self.model, "model identifier", 256)
        if not 0 < len(self.messages) <= DEFAULT_LIMITS.message_count:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "message count is outside its limit"))
        if len(self.tools) > DEFAULT_LIMITS.advertised_tool_count:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "advertised tool count exceeded"))
        if len({tool.name for tool in self.tools}) != len(self.tools):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "duplicate advertised tool name"))
        if not isinstance(self.max_output_tokens, int) or isinstance(self.max_output_tokens, bool) or not 0 < self.max_output_tokens <= 8_192:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "output budget is invalid"))
        if not isinstance(self.correlation_id, RequestCorrelationId):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "correlation ID is not project-owned"))

    def to_json_bytes(self, limits: Limits = DEFAULT_LIMITS) -> bytes:
        if len(self.messages) > limits.message_count:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "message count exceeds configured limit"))
        if len(self.tools) > limits.advertised_tool_count:
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "advertised tool count exceeds configured limit"))
        for message in self.messages:
            if len(message.content.encode("utf-8", "replace")) > limits.message_bytes:
                raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "message exceeds configured byte limit"))
        value: dict[str, Any] = {
            "correlationId": str(self.correlation_id),
            "model": self.model,
            "messages": [{"role": item.role.value, "content": item.content} for item in self.messages],
            "tools": [
                {"name": item.name, "description": item.description, "parameters": item.parameters}
                for item in self.tools
            ],
            "maxOutputTokens": self.max_output_tokens,
        }
        for item in value["tools"]:
            definition_bytes = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(definition_bytes) > limits.tool_definition_bytes:
                raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "tool definition exceeds configured byte limit"))
        generation = {
            key: value
            for key, value in {
                "temperature": self.generation.temperature,
                "topP": self.generation.top_p,
                "seed": self.generation.seed,
            }.items()
            if value is not None
        }
        if generation:
            value["generation"] = generation
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > limits.provider_request_bytes:
            raise ContractError(failure(FailureClass.REQUEST_TOO_LARGE, "provider request exceeds byte limit"))
        return encoded


@dataclass(frozen=True)
class ProviderFinalMessage:
    message: ProviderMessage


@dataclass(frozen=True)
class ProviderToolCallProposal:
    call_id: ToolCallId
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, ToolCallId):
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "call ID is not project-owned"))
        _identifier(self.name, "tool name", FailureClass.INVALID_TOOL_PROPOSAL)
        if not isinstance(self.arguments, dict):
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments must be an object"))
        _json_value(dict(self.arguments))

    @property
    def action_identity(self) -> "LocalActionIdentity":
        canonical = json.dumps({"name": self.name, "arguments": self.arguments}, sort_keys=True, separators=(",", ":"))
        return LocalActionIdentity(hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32])


@dataclass(frozen=True)
class LocalActionIdentity:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or len(self.value) != 32 or any(char not in "0123456789abcdef" for char in self.value):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "action identity is not canonical"))


def _validate_schema(value: Any, schema: Mapping[str, Any], limits: Limits) -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments have the wrong type"))
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool schema is malformed"))
        if any(key not in properties for key in value) and schema.get("additionalProperties", False) is not True:
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments contain unknown fields"))
        if any(item not in value for item in required):
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments omit required fields"))
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                _validate_schema(child, child_schema, limits)
    elif schema_type == "string" and not isinstance(value, str):
        raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument is not a string"))
    elif schema_type == "boolean" and not isinstance(value, bool):
        raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument is not a boolean"))
    elif schema_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument is not an integer"))
    elif schema_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument is not a number"))
    elif schema_type == "array" and (not isinstance(value, list) or len(value) > limits.object_array_items):
        raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument is not a bounded array"))


def parse_provider_response(
    raw: bytes | str,
    *,
    advertised_tools: Sequence[AdvertisedTool] = (),
    limits: Limits = DEFAULT_LIMITS,
) -> ProviderFinalMessage | tuple[ProviderToolCallProposal, ...]:
    try:
        value = parse_closed_json(raw, limits)
        if not isinstance(value, dict):
            raise ContractError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "response must be an object"))
        if "message" in value:
            body = _closed_object(value, {"message"}, {"message"}, "provider response") ["message"]
            message = _closed_object(body, {"role", "content"}, {"role", "content"}, "final message")
            if message["role"] != MessageRole.ASSISTANT.value or not isinstance(message["content"], str):
                raise ContractError(failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "final response is not an assistant message"))
            return ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT, _bounded_text(message["content"], "final content", limits.message_bytes)))
        calls_value = _closed_object(value, {"toolCalls"}, {"toolCalls"}, "provider response")["toolCalls"]
        if not isinstance(calls_value, list) or not calls_value or len(calls_value) > limits.proposed_tool_call_count:
            raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool-call count is outside its limit"))
        tools_by_name = {tool.name: tool for tool in advertised_tools}
        seen: set[str] = set()
        calls: list[ProviderToolCallProposal] = []
        for item in calls_value:
            call = _closed_object(item, {"id", "name", "arguments"}, {"id", "name", "arguments"}, "tool proposal")
            _bounded_text(call["arguments"], "tool arguments JSON", limits.tool_argument_bytes, FailureClass.INVALID_TOOL_PROPOSAL)
            arguments_value = parse_closed_json(call["arguments"], limits)
            if not isinstance(arguments_value, dict):
                raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments JSON must be an object"))
            call_id = ToolCallId(call["id"])
            if str(call_id) in seen:
                raise ContractError(failure(FailureClass.REPLAY_OR_DUPLICATE_PROPOSAL, "duplicate tool call identifier"))
            seen.add(str(call_id))
            name = _bounded_text(call["name"], "tool name", 256, FailureClass.INVALID_TOOL_PROPOSAL)
            if tools_by_name and name not in tools_by_name:
                raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool is not exactly advertised"))
            if name in tools_by_name:
                _validate_schema(arguments_value, tools_by_name[name].parameters, limits)
            calls.append(ProviderToolCallProposal(call_id, name, arguments_value))
        return tuple(calls)
    except ProviderError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        detail = str(error).encode("utf-8", "replace")[:128].decode("utf-8", "ignore")
        raise ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, detail)) from None


@dataclass(frozen=True)
class RetryDecisionValue:
    decision: RetryDecision
