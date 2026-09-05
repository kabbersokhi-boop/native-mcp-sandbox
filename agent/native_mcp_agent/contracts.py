"""Provider-neutral closed contracts and bounded JSON parsing."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, HARD_LIMITS, Limits
from .retry import RetryDecision


class ContractError(ProviderError):
    pass


_CORRELATION_ID = re.compile(r"^req-[0-9]+(?:-[0-9]+)*$")
_CANONICAL_CALL_ID = re.compile(r"^call-[0-9]+$")
_LEGACY_CALL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PROJECT_ID_MARKERS = (
    "authorization",
    "proxy-authorization",
    "bearer",
    "api-key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
    "header",
    "path",
    "userinfo",
    "user-info",
    "sk-",
    "pk-",
    "rk-",
    "://",
    "http",
    "ftp",
)
_REQUEST_ID_COUNTER = 0
_REQUEST_ID_LOCK = threading.Lock()


def _has_project_id_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PROJECT_ID_MARKERS) or any(
        marker in value for marker in ("/", "\\", "@", "?", "#", ":")
    )


def _canonical_correlation_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or len(value.encode("ascii", "strict")) > 64
        or not _CORRELATION_ID.fullmatch(value)
    ):
        raise ContractError(
            failure(
                FailureClass.LOCAL_VALIDATION_FAILURE, "request correlation ID is not project-owned"
            )
        )
    return value


class RequestCorrelationId(str):
    def __new__(cls, value: str) -> RequestCorrelationId:
        return str.__new__(cls, _canonical_correlation_id(value))

    @classmethod
    def new(cls) -> RequestCorrelationId:
        global _REQUEST_ID_COUNTER
        with _REQUEST_ID_LOCK:
            _REQUEST_ID_COUNTER += 1
            return cls(f"req-{_REQUEST_ID_COUNTER}")

    create = new


def new_request_correlation_id() -> RequestCorrelationId:
    """Create a local project-owned correlation ID."""
    return RequestCorrelationId.new()


class ToolCallId(str):
    def __new__(cls, value: str) -> ToolCallId:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value
            or len(value.encode("ascii", "strict")) > 128
        ):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool call ID is not project-owned")
            )
        if _CANONICAL_CALL_ID.fullmatch(value):
            return str.__new__(cls, value)
        if _has_project_id_marker(value) or not _LEGACY_CALL_ID.fullmatch(value):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool call ID is not project-owned")
            )
        digest = hashlib.sha256(value.encode("ascii")).hexdigest()[:32]
        return str.__new__(cls, f"call-{digest}")

    @classmethod
    def require_canonical(cls, value: Any) -> ToolCallId:
        if not isinstance(value, str) or not _CANONICAL_CALL_ID.fullmatch(value):
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "transcript proposal ID is not canonical"
                )
            )
        return cls(value)


class ModelIdentifier(str):
    """A provider-neutral, credential-free model identifier."""

    _GRAMMAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:[/:][A-Za-z0-9][A-Za-z0-9._-]*)*$")
    _SUSPICIOUS = (
        "authorization",
        "apikey",
        "api-key",
        "bearer",
        "credential",
        "password",
        "secret",
        "token",
    )

    def __new__(cls, value: str) -> ModelIdentifier:
        try:
            size = len(value.encode("ascii")) if isinstance(value, str) else -1
        except UnicodeEncodeError:
            size = -1
        lowered = value.lower() if isinstance(value, str) else ""
        if (
            not isinstance(value, str)
            or not value
            or size < 0
            or size > 256
            or not value.isascii()
            or not cls._GRAMMAR.fullmatch(value)
            or value.startswith(("/", "\\"))
            or "://" in value
            or any(marker in lowered for marker in cls._SUSPICIOUS)
            or lowered.startswith(("http:", "https:", "ftp:", "file:"))
        ):
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "model identifier is not project-owned"
                )
            )
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
    try:
        size = len(value.encode("utf-8")) if isinstance(value, str) else -1
    except UnicodeEncodeError:
        size = -1
    if (
        not isinstance(value, str)
        or not value
        or size > 64
        or size < 0
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for char in value
        )
        or not value[0].isalnum()
    ):
        raise ContractError(failure(classification, f"{label} must be a bounded non-empty string"))


def _bounded_text(
    value: Any,
    label: str,
    maximum: int,
    classification: FailureClass = FailureClass.LOCAL_VALIDATION_FAILURE,
) -> str:
    try:
        size = len(value.encode("utf-8")) if isinstance(value, str) else -1
    except UnicodeEncodeError:
        size = -1
    if not isinstance(value, str) or not value or size > maximum or size < 0:
        raise ContractError(
            failure(classification, f"{label} is empty, incorrectly typed, or oversized")
        )
    return value


class _FrozenDict(dict[str, Any]):
    """A JSON-compatible dict whose public mutation operations are disabled."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable JSON mapping")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable


def _json_string_limit(limits: Limits, string_bytes: int | None) -> int:
    if string_bytes is None:
        return max(limits.message_bytes, limits.tool_argument_bytes, limits.tool_definition_bytes)
    if isinstance(string_bytes, bool) or not isinstance(string_bytes, int) or string_bytes <= 0:
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON string bound is invalid")
        )
    return string_bytes


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and (isinstance(value, int) or math.isfinite(value))
    )


def _freeze_json(
    value: Any, *, depth: int = 0, limits: Limits = HARD_LIMITS, string_bytes: int | None = None
) -> Any:
    """Validate JSON and detach it from caller-owned containers."""
    if depth > limits.json_nesting_depth:
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON nesting depth exceeded")
        )
    if isinstance(value, Mapping):
        if len(value) > limits.object_array_items:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON object item limit exceeded")
            )
        result = _FrozenDict()
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ContractError(
                    failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON object key is invalid")
                )
            dict.__setitem__(
                result,
                key,
                _freeze_json(child, depth=depth + 1, limits=limits, string_bytes=string_bytes),
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > limits.object_array_items:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON array item limit exceeded")
            )
        return tuple(
            _freeze_json(child, depth=depth + 1, limits=limits, string_bytes=string_bytes)
            for child in value
        )
    if isinstance(value, str):
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON string is not valid UTF-8")
            ) from None
        if size > _json_string_limit(limits, string_bytes):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON string exceeds byte limit")
            )
        return value
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "non-finite JSON number")
            )
        return value
    raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "unsupported JSON value"))


def _json_value(
    value: Any, *, depth: int = 0, limits: Limits = DEFAULT_LIMITS, string_bytes: int | None = None
) -> None:
    if depth > limits.json_nesting_depth:
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON nesting depth exceeded")
        )
    if isinstance(value, Mapping):
        if len(value) > limits.object_array_items:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON object item limit exceeded")
            )
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ContractError(
                    failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON object key is invalid")
                )
            _json_value(child, depth=depth + 1, limits=limits, string_bytes=string_bytes)
    elif isinstance(value, (list, tuple)):
        if len(value) > limits.object_array_items:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON array item limit exceeded")
            )
        for child in value:
            _json_value(child, depth=depth + 1, limits=limits, string_bytes=string_bytes)
    elif isinstance(value, str):
        try:
            if len(value.encode("utf-8")) > _json_string_limit(limits, string_bytes):
                raise ContractError(
                    failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON string exceeds byte limit")
                )
        except UnicodeEncodeError:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "JSON string is not valid UTF-8")
            ) from None
    elif isinstance(value, (int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "non-finite JSON number")
            )
    else:
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, "unsupported JSON value")
        )


def _pairs_reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(
                failure(FailureClass.DUPLICATE_KEY_JSON, "duplicate JSON object key")
            )
        result[key] = value
    return result


def parse_closed_json(
    raw: bytes | str,
    limits: Limits = DEFAULT_LIMITS,
    *,
    byte_limit: int | None = None,
    string_bytes: int | None = None,
) -> Any:
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    except UnicodeEncodeError:
        raise ContractError(
            failure(FailureClass.MALFORMED_JSON, "JSON input is not valid UTF-8")
        ) from None
    if not isinstance(encoded, bytes):
        raise ContractError(failure(FailureClass.MALFORMED_JSON, "JSON input is not bytes or text"))
    bound = limits.provider_response_bytes if byte_limit is None else byte_limit
    if len(encoded) > bound:
        raise ContractError(
            failure(FailureClass.OVERSIZED_RESPONSE, "JSON input exceeds response limit")
        )
    try:
        value = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_pairs_reject_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, TypeError):
        raise ContractError(
            failure(FailureClass.MALFORMED_JSON, "JSON input is malformed")
        ) from None
    _json_value(value, limits=limits, string_bytes=string_bytes)
    return value


def _reject_nonfinite(_value: str) -> None:
    raise ValueError


def _closed_object(value: Any, allowed: set[str], required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} must be an object")
        )
    unknown = set(value) - allowed
    if unknown:
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} contains unknown fields")
        )
    missing = required - set(value)
    if missing:
        raise ContractError(
            failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} is missing required fields")
        )
    return value


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str
    model: ModelIdentifier | str
    verify_tls: bool = True
    allow_loopback_http: bool = False
    redirects: str = "reject"

    def __post_init__(self) -> None:
        _bounded_text(
            self.endpoint, "provider endpoint", 2_048, FailureClass.INVALID_PROVIDER_CONFIGURATION
        )
        try:
            model = (
                self.model
                if isinstance(self.model, ModelIdentifier)
                else ModelIdentifier(self.model)
            )
        except ContractError as error:
            raise ProviderError(
                failure(FailureClass.INVALID_PROVIDER_CONFIGURATION, "model identifier is invalid")
            ) from error
        object.__setattr__(self, "model", model)
        if not isinstance(self.verify_tls, bool) or not isinstance(self.allow_loopback_http, bool):
            raise ContractError(
                failure(
                    FailureClass.INVALID_PROVIDER_CONFIGURATION,
                    "TLS and loopback options must be boolean",
                )
            )
        if self.redirects != "reject":
            raise ContractError(
                failure(
                    FailureClass.INVALID_PROVIDER_CONFIGURATION, "redirect mode is not supported"
                )
            )


@dataclass(frozen=True)
class ProviderMessage:
    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, MessageRole):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "message role is invalid")
            )
        _bounded_text(self.content, "message content", HARD_LIMITS.message_bytes)


@dataclass(frozen=True)
class GenerationControls:
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.temperature, "temperature"), (self.top_p, "top_p")):
            if value is not None and (not _finite_number(value) or not 0.0 <= value <= 2.0):
                raise ContractError(
                    failure(FailureClass.LOCAL_VALIDATION_FAILURE, f"{label} is invalid")
                )
        if self.seed is not None and (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= 2**31 - 1
        ):
            raise ContractError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "seed is invalid"))


@dataclass(frozen=True)
class AdvertisedTool:
    name: str
    parameters: Mapping[str, Any]
    description: str = ""

    def __post_init__(self) -> None:
        _identifier(self.name, "tool name", FailureClass.LOCAL_VALIDATION_FAILURE)
        if not isinstance(self.parameters, Mapping):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "tool parameters must be an object")
            )
        frozen = _freeze_json(self.parameters, limits=HARD_LIMITS)
        if not isinstance(frozen, dict):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "tool parameters must be an object")
            )
        object.__setattr__(self, "parameters", frozen)
        _validate_schema_definition(frozen, HARD_LIMITS)
        if not isinstance(self.description, str):
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "tool description is incorrectly typed"
                )
            )
        if self.description and len(self.description.encode("utf-8")) > 1_024:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "tool description is oversized")
            )


@dataclass(frozen=True)
class ProviderRequest:
    model: ModelIdentifier | str
    messages: tuple[ProviderMessage, ...]
    tools: tuple[AdvertisedTool, ...]
    max_output_tokens: int
    correlation_id: RequestCorrelationId
    generation: GenerationControls = field(default_factory=GenerationControls)

    def __post_init__(self) -> None:
        try:
            model = (
                self.model
                if isinstance(self.model, ModelIdentifier)
                else ModelIdentifier(self.model)
            )
        except ContractError as error:
            raise ProviderError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "model identifier is invalid")
            ) from error
        object.__setattr__(self, "model", model)
        if (
            not isinstance(self.messages, tuple)
            or not 0 < len(self.messages) <= HARD_LIMITS.message_count
        ):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "message count is outside its limit")
            )
        if not isinstance(self.tools, tuple) or len(self.tools) > HARD_LIMITS.advertised_tool_count:
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "advertised tool count exceeded")
            )
        if any(not isinstance(message, ProviderMessage) for message in self.messages) or any(
            not isinstance(tool, AdvertisedTool) for tool in self.tools
        ):
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "provider request members are invalid"
                )
            )
        if len({tool.name for tool in self.tools}) != len(self.tools):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "duplicate advertised tool name")
            )
        if (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or not 0 < self.max_output_tokens <= 8_192
        ):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "output budget is invalid")
            )
        if not isinstance(self.correlation_id, RequestCorrelationId):
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "correlation ID is not project-owned"
                )
            )

    def to_json_bytes(self, limits: Limits = DEFAULT_LIMITS) -> bytes:
        model = ModelIdentifier(self.model)
        if not isinstance(self.correlation_id, RequestCorrelationId):
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "correlation ID is not project-owned"
                )
            )
        RequestCorrelationId(str(self.correlation_id))
        if len(self.messages) > limits.message_count:
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "message count exceeds configured limit"
                )
            )
        if len(self.tools) > limits.advertised_tool_count:
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE,
                    "advertised tool count exceeds configured limit",
                )
            )
        if any(
            not isinstance(item, ProviderMessage)
            or not isinstance(item.role, MessageRole)
            or not isinstance(item.content, str)
            for item in self.messages
        ):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "provider message is invalid")
            )
        for item in self.tools:
            if (
                not isinstance(item, AdvertisedTool)
                or not isinstance(item.name, str)
                or not isinstance(item.parameters, Mapping)
            ):
                raise ContractError(
                    failure(FailureClass.LOCAL_VALIDATION_FAILURE, "advertised tool is invalid")
                )
            _identifier(item.name, "tool name", FailureClass.LOCAL_VALIDATION_FAILURE)
            _validate_schema_definition(item.parameters, limits)
        for message in self.messages:
            if len(message.content.encode("utf-8", "replace")) > limits.message_bytes:
                raise ContractError(
                    failure(
                        FailureClass.LOCAL_VALIDATION_FAILURE,
                        "message exceeds configured byte limit",
                    )
                )
        if len(model.encode("ascii")) > limits.message_bytes:
            raise ContractError(
                failure(
                    FailureClass.LOCAL_VALIDATION_FAILURE, "model exceeds configured byte limit"
                )
            )
        value: dict[str, Any] = {
            "correlationId": str(self.correlation_id),
            "model": str(model),
            "messages": [
                {"role": item.role.value, "content": item.content} for item in self.messages
            ],
            "tools": [
                {"name": item.name, "description": item.description, "parameters": item.parameters}
                for item in self.tools
            ],
            "maxOutputTokens": self.max_output_tokens,
        }
        for item in value["tools"]:
            _validate_schema_definition(item["parameters"], limits)
            _json_value(item["parameters"], limits=limits)
            definition_bytes = json.dumps(
                item, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            if len(definition_bytes) > limits.tool_definition_bytes:
                raise ContractError(
                    failure(
                        FailureClass.LOCAL_VALIDATION_FAILURE,
                        "tool definition exceeds configured byte limit",
                    )
                )
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
        encoded = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > limits.provider_request_bytes:
            raise ContractError(
                failure(FailureClass.REQUEST_TOO_LARGE, "provider request exceeds byte limit")
            )
        return encoded


@dataclass(frozen=True)
class ProviderFinalMessage:
    message: ProviderMessage


@dataclass(frozen=True)
class ProviderToolCallProposal:
    call_id: ToolCallId
    name: str
    arguments: Mapping[str, Any]
    _canonical_argument_bytes: bytes = field(init=False, repr=False, compare=False)
    _action_identity: LocalActionIdentity | None = field(
        init=False, repr=False, compare=False, default=None
    )

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, ToolCallId):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "call ID is not project-owned")
            )
        _identifier(self.name, "tool name", FailureClass.INVALID_TOOL_PROPOSAL)
        if not isinstance(self.arguments, Mapping):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments must be an object")
            )
        frozen = _freeze_json(self.arguments, limits=HARD_LIMITS)
        if not isinstance(frozen, dict):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments must be an object")
            )
        object.__setattr__(self, "arguments", frozen)
        _json_value(frozen, limits=HARD_LIMITS)
        try:
            encoded = json.dumps(
                frozen, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments are not canonical JSON")
            ) from None
        if len(encoded) > HARD_LIMITS.tool_argument_bytes:
            raise ContractError(
                failure(
                    FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments exceed their byte limit"
                )
            )
        canonical = json.dumps(
            {"name": self.name, "arguments": frozen},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "_canonical_argument_bytes", encoded)
        object.__setattr__(
            self,
            "_action_identity",
            LocalActionIdentity(hashlib.sha256(canonical).hexdigest()[:32]),
        )

    @property
    def action_identity(self) -> LocalActionIdentity:
        if not isinstance(self._action_identity, LocalActionIdentity):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "action identity is not canonical")
            )
        return self._action_identity

    @property
    def canonical_argument_bytes(self) -> bytes:
        return self._canonical_argument_bytes

    def to_json_bytes(self, limits: Limits = DEFAULT_LIMITS) -> bytes:
        """Serialize a proposal only after revalidating its control scalars."""
        if not isinstance(self.call_id, ToolCallId) or not _CANONICAL_CALL_ID.fullmatch(
            str(self.call_id)
        ):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "call ID is not canonical")
            )
        _identifier(self.name, "tool name", FailureClass.INVALID_TOOL_PROPOSAL)
        frozen = _freeze_json(self.arguments, limits=limits)
        if not isinstance(frozen, dict):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments are not an object")
            )
        encoded = json.dumps(
            {"id": str(self.call_id), "name": self.name, "arguments": frozen},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > limits.tool_argument_bytes:
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool proposal exceeds its byte limit")
            )
        return encoded


@dataclass(frozen=True)
class LocalActionIdentity:
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != 32
            or any(char not in "0123456789abcdef" for char in self.value)
        ):
            raise ContractError(
                failure(FailureClass.LOCAL_VALIDATION_FAILURE, "action identity is not canonical")
            )


_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "additionalProperties",
}
_SCHEMA_TYPES = {"object", "array", "string", "boolean", "integer", "number", "null"}


def _schema_error(detail: str = "tool schema is malformed") -> ContractError:
    return ContractError(failure(FailureClass.INVALID_TOOL_PROPOSAL, detail))


def _validate_schema_definition(schema: Any, limits: Limits, *, depth: int = 0) -> None:
    if not isinstance(schema, dict) or depth > limits.json_nesting_depth:
        raise _schema_error()
    if any(not isinstance(key, str) or key not in _SCHEMA_KEYS for key in schema):
        raise _schema_error()
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _SCHEMA_TYPES:
        raise _schema_error()
    if "additionalProperties" in schema and schema["additionalProperties"] is not False:
        raise _schema_error()
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or len(properties) > limits.object_array_items:
            raise _schema_error()
        if "additionalProperties" not in schema and schema_type == "object":
            # The project subset is closed by default, but emitted schemas are
            # canonicalized with an explicit false value by callers.
            pass
        for name, child in properties.items():
            try:
                name_size = len(name.encode("utf-8")) if isinstance(name, str) else -1
            except UnicodeEncodeError:
                name_size = -1
            if (
                not isinstance(name, str)
                or not name
                or name_size > 64
                or name_size < 0
                or any(ord(char) < 0x21 or char in "/\\" for char in name)
            ):
                raise _schema_error()
            _validate_schema_definition(child, limits, depth=depth + 1)
        if not isinstance(required, (list, tuple)) or len(required) > limits.object_array_items:
            raise _schema_error()
        if (
            any(not isinstance(name, str) for name in required)
            or len(set(required)) != len(required)
            or any(name not in properties for name in required)
        ):
            raise _schema_error()
    elif schema_type == "array":
        if not isinstance(schema.get("items"), dict):
            raise _schema_error()
        _validate_schema_definition(schema["items"], limits, depth=depth + 1)
    elif any(key in schema for key in ("properties", "required", "items", "additionalProperties")):
        raise _schema_error()
    if "enum" in schema:
        values = schema["enum"]
        if (
            not isinstance(values, (list, tuple))
            or not values
            or len(values) > limits.object_array_items
        ):
            raise _schema_error()
        _json_value(values, limits=limits)
        for item in values:
            if not _schema_value_matches(item, schema_type):
                raise _schema_error()
    for key in ("minLength", "maxLength"):
        if key in schema and (
            schema_type != "string"
            or isinstance(schema[key], bool)
            or not isinstance(schema[key], int)
            or schema[key] < 0
            or schema[key] > HARD_LIMITS.tool_argument_bytes
        ):
            raise _schema_error()
    if (
        "minLength" in schema
        and "maxLength" in schema
        and schema["minLength"] > schema["maxLength"]
    ):
        raise _schema_error()
    for key in ("minimum", "maximum"):
        if key in schema and (
            schema_type not in {"integer", "number"} or not _finite_number(schema[key])
        ):
            raise _schema_error()
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        raise _schema_error()


def _schema_value_matches(value: Any, schema_type: str) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return _finite_number(value)
    if schema_type == "object":
        return isinstance(value, Mapping)
    if schema_type == "array":
        return isinstance(value, (list, tuple))
    return value is None


def _validate_schema(value: Any, schema: Mapping[str, Any], limits: Limits) -> None:
    _validate_schema_definition(schema, limits)
    schema_type = schema["type"]
    if not _schema_value_matches(value, schema_type):
        raise ContractError(
            failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument has the wrong type")
        )
    if "enum" in schema and not any(
        type(value) is type(item) and value == item for item in schema["enum"]
    ):
        raise ContractError(
            failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument is outside its enum")
        )
    if schema_type == "object":
        if len(value) > limits.object_array_items or set(value) - set(schema.get("properties", {})):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments contain unknown fields")
            )
        if any(item not in value for item in schema.get("required", [])):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments omit required fields")
            )
        for key, child in value.items():
            _validate_schema(child, schema["properties"][key], limits)
    elif schema_type == "array":
        if len(value) > limits.object_array_items:
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool argument array is oversized")
            )
        for child in value:
            _validate_schema(child, schema["items"], limits)
    elif schema_type == "string":
        size = len(value.encode("utf-8"))
        if size < schema.get("minLength", 0) or size > min(
            schema.get("maxLength", limits.tool_argument_bytes), limits.tool_argument_bytes
        ):
            raise ContractError(
                failure(
                    FailureClass.INVALID_TOOL_PROPOSAL, "tool argument string is outside its bound"
                )
            )
    elif schema_type in {"integer", "number"}:
        if (
            not _finite_number(value)
            or ("minimum" in schema and value < schema["minimum"])
            or ("maximum" in schema and value > schema["maximum"])
        ):
            raise ContractError(
                failure(
                    FailureClass.INVALID_TOOL_PROPOSAL, "tool argument number is outside its bound"
                )
            )


def parse_provider_response(
    raw: bytes | str,
    *,
    advertised_tools: Sequence[AdvertisedTool] = (),
    limits: Limits = DEFAULT_LIMITS,
) -> ProviderFinalMessage | tuple[ProviderToolCallProposal, ...]:
    try:
        value = parse_closed_json(raw, limits)
        if not isinstance(value, dict):
            raise ContractError(
                failure(FailureClass.UNSUPPORTED_PROVIDER_CONTENT, "response must be an object")
            )
        if "message" in value:
            body = _closed_object(value, {"message"}, {"message"}, "provider response")["message"]
            message = _closed_object(
                body, {"role", "content"}, {"role", "content"}, "final message"
            )
            if message["role"] != MessageRole.ASSISTANT.value or not isinstance(
                message["content"], str
            ):
                raise ContractError(
                    failure(
                        FailureClass.UNSUPPORTED_PROVIDER_CONTENT,
                        "final response is not an assistant message",
                    )
                )
            return ProviderFinalMessage(
                ProviderMessage(
                    MessageRole.ASSISTANT,
                    _bounded_text(message["content"], "final content", limits.message_bytes),
                )
            )
        calls_value = _closed_object(value, {"toolCalls"}, {"toolCalls"}, "provider response")[
            "toolCalls"
        ]
        if (
            not isinstance(calls_value, list)
            or not calls_value
            or len(calls_value) > limits.proposed_tool_call_count
        ):
            raise ContractError(
                failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool-call count is outside its limit")
            )
        tools_by_name = {tool.name: tool for tool in advertised_tools}
        seen: set[str] = set()
        calls: list[ProviderToolCallProposal] = []
        for item in calls_value:
            call = _closed_object(
                item, {"id", "name", "arguments"}, {"id", "name", "arguments"}, "tool proposal"
            )
            _bounded_text(
                call["arguments"],
                "tool arguments JSON",
                limits.tool_argument_bytes,
                FailureClass.INVALID_TOOL_PROPOSAL,
            )
            arguments_value = parse_closed_json(call["arguments"], limits)
            if not isinstance(arguments_value, dict):
                raise ContractError(
                    failure(
                        FailureClass.INVALID_TOOL_PROPOSAL, "tool arguments JSON must be an object"
                    )
                )
            call_id = ToolCallId(call["id"])
            if str(call_id) in seen:
                raise ContractError(
                    failure(
                        FailureClass.REPLAY_OR_DUPLICATE_PROPOSAL, "duplicate tool call identifier"
                    )
                )
            seen.add(str(call_id))
            name = _bounded_text(call["name"], "tool name", 256, FailureClass.INVALID_TOOL_PROPOSAL)
            if not tools_by_name or name not in tools_by_name:
                raise ContractError(
                    failure(FailureClass.INVALID_TOOL_PROPOSAL, "tool is not exactly advertised")
                )
            if name in tools_by_name:
                _validate_schema(arguments_value, tools_by_name[name].parameters, limits)
            calls.append(ProviderToolCallProposal(call_id, name, arguments_value))
        return tuple(calls)
    except ProviderError:
        raise
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ):
        raise ContractError(
            failure(FailureClass.INVALID_TOOL_PROPOSAL, "provider response is malformed")
        ) from None


@dataclass(frozen=True)
class RetryDecisionValue:
    decision: RetryDecision
