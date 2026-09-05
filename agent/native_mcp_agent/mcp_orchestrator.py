"""Closed, serial and deadline-bounded offline MCP orchestration."""

from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from .contracts import (
    AdvertisedTool,
    EvidenceProvenance,
    LocalActionIdentity,
    ProviderFinalMessage,
    ProviderRequest,
    ProviderToolCallProposal,
    _freeze_json,
    _validate_schema,
    parse_closed_json,
)
from .environment import build_child_environment
from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, Limits
from .redaction import redact_json
from .transcript import BoundedTranscript, parse_bounded_transcript


class McpError(ProviderError):
    pass


def _fail(kind: FailureClass, detail: str) -> McpError:
    return McpError(failure(kind, detail))


def _canon(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_CLIENT_VERSION = "0.11.0"
_TOOL_FIELDS = {
    "name",
    "title",
    "description",
    "inputSchema",
    "outputSchema",
    "annotations",
    "execution",
    "icons",
    "_meta",
}
_INPUT_SCHEMA_FIELDS = {
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
    "description",
    "default",
    "title",
}
_OUTPUT_SCHEMA_FIELDS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "maxItems",
    "additionalProperties",
}
_OUTPUT_SCHEMA_TYPES = {"object", "array", "string", "boolean", "integer", "number", "null"}
_MIN_MCP_INTEGER = -(2**63)
_MAX_MCP_INTEGER = 2**64 - 1


def _closed(value: Any, allowed: set[str], required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "closed schema rejected")
    return value


def _bounded_mcp_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, int):
        return _MIN_MCP_INTEGER <= value <= _MAX_MCP_INTEGER
    return math.isfinite(value)


def _mcp_evidence_limits(limits: Limits) -> Limits:
    return replace(limits, object_array_items=limits.mcp_evidence_items)


def _normalize_input_schema(schema: Any, limits: Limits, depth: int = 0) -> Mapping[str, Any]:
    if (
        not isinstance(schema, dict)
        or depth > limits.json_nesting_depth
        or set(schema) - _INPUT_SCHEMA_FIELDS
    ):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool input schema is unsupported")
    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"description", "default", "title"}:
            continue
        if key == "properties":
            if not isinstance(value, dict) or len(value) > limits.object_array_items:
                raise _fail(
                    FailureClass.MCP_PROTOCOL_FAILURE, "tool input schema properties are invalid"
                )
            normalized[key] = {
                name: _normalize_input_schema(child, limits, depth + 1)
                for name, child in value.items()
            }
        elif key == "items":
            normalized[key] = _normalize_input_schema(value, limits, depth + 1)
        else:
            normalized[key] = value
    frozen = _freeze_json(normalized, limits=limits)
    if not isinstance(frozen, dict):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool input schema is invalid")
    return frozen


def _schema_types(schema: Mapping[str, Any]) -> tuple[str, ...]:
    raw = schema.get("type")
    if isinstance(raw, str):
        values = (raw,)
    elif isinstance(raw, (list, tuple)) and raw and all(isinstance(item, str) for item in raw):
        values = tuple(raw)
    else:
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema type is invalid")
    if len(set(values)) != len(values) or any(item not in _OUTPUT_SCHEMA_TYPES for item in values):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema type is unsupported")
    return values


def _schema_type_matches(value: Any, schema_type: str) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool) and _bounded_mcp_number(value)
    if schema_type == "number":
        return _bounded_mcp_number(value)
    if schema_type == "object":
        return isinstance(value, Mapping)
    if schema_type == "array":
        return isinstance(value, (list, tuple))
    return value is None


def _validate_output_schema_definition(
    schema: Any, limits: Limits, depth: int = 0
) -> Mapping[str, Any]:
    if (
        not isinstance(schema, dict)
        or depth > limits.json_nesting_depth
        or set(schema) - _OUTPUT_SCHEMA_FIELDS
    ):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema is unsupported")
    schema_types = _schema_types(schema)
    object_fields = {"properties", "required", "additionalProperties"}
    if "object" in schema_types:
        if schema.get("additionalProperties") is not False:
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema must be closed")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or len(properties) > limits.object_array_items:
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema properties are invalid"
            )
        if (
            not isinstance(required, (list, tuple))
            or len(required) > limits.object_array_items
            or any(not isinstance(item, str) for item in required)
            or len(set(required)) != len(required)
            or any(item not in properties for item in required)
        ):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema required fields are invalid"
            )
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise _fail(
                    FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema property name is invalid"
                )
            _validate_output_schema_definition(child, limits, depth + 1)
    elif any(key in schema for key in object_fields):
        raise _fail(
            FailureClass.MCP_PROTOCOL_FAILURE,
            "tool output schema has object keywords for a non-object",
        )
    if "array" in schema_types:
        if not isinstance(schema.get("items"), dict):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool output array schema is missing items"
            )
        if (
            isinstance(schema.get("maxItems"), bool)
            or not isinstance(schema.get("maxItems"), int)
            or schema["maxItems"] < 0
            or schema["maxItems"] > limits.mcp_evidence_items
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output array bound is invalid")
        _validate_output_schema_definition(schema["items"], limits, depth + 1)
    elif "items" in schema or "maxItems" in schema:
        raise _fail(
            FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema has array items for a non-array"
        )
    if "enum" in schema:
        values = schema["enum"]
        if (
            not isinstance(values, (list, tuple))
            or not values
            or len(values) > limits.object_array_items
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema enum is invalid")
        if any(
            not any(_schema_type_matches(item, schema_type) for schema_type in schema_types)
            for item in values
        ):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema enum type is invalid"
            )
    for key in ("minLength", "maxLength"):
        if key in schema and (
            "string" not in schema_types
            or isinstance(schema[key], bool)
            or not isinstance(schema[key], int)
            or schema[key] < 0
            or schema[key] > limits.mcp_response_bytes
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output string bound is invalid")
    if (
        "minLength" in schema
        and "maxLength" in schema
        and schema["minLength"] > schema["maxLength"]
    ):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output string bounds are reversed")
    for key in ("minimum", "maximum"):
        if key in schema and (
            not ({"integer", "number"} & set(schema_types)) or not _bounded_mcp_number(schema[key])
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output number bound is invalid")
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output number bounds are reversed")
    frozen = _freeze_json(schema, limits=limits)
    if not isinstance(frozen, dict):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schema is invalid")
    return frozen


def _validate_output_value(
    value: Any, schema: Mapping[str, Any], limits: Limits, depth: int = 0
) -> None:
    if depth > limits.json_nesting_depth:
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool structured output is too deep")
    schema_types = _schema_types(schema)
    matching = next((item for item in schema_types if _schema_type_matches(value, item)), None)
    if matching is None:
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool structured output has the wrong type")
    if "enum" in schema and not any(
        type(value) is type(item) and value == item for item in schema["enum"]
    ):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool structured output is outside its enum")
    if matching == "object":
        properties = schema.get("properties", {})
        if len(value) > limits.object_array_items or set(value) - set(properties):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool structured output contains unknown fields"
            )
        if any(item not in value for item in schema.get("required", [])):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool structured output omits required fields"
            )
        for key, child in value.items():
            _validate_output_value(child, properties[key], limits, depth + 1)
    elif matching == "array":
        if len(value) > schema["maxItems"]:
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE, "tool structured output array is oversized"
            )
        for child in value:
            _validate_output_value(child, schema["items"], limits, depth + 1)
    elif matching == "string":
        size = len(value.encode("utf-8"))
        if size < schema.get("minLength", 0) or size > min(
            schema.get("maxLength", limits.mcp_response_bytes), limits.mcp_response_bytes
        ):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE,
                "tool structured output string is outside its bound",
            )
    elif matching in {"integer", "number"}:
        if ("minimum" in schema and value < schema["minimum"]) or (
            "maximum" in schema and value > schema["maximum"]
        ):
            raise _fail(
                FailureClass.MCP_PROTOCOL_FAILURE,
                "tool structured output number is outside its bound",
            )


@dataclass(frozen=True)
class Deadline:
    absolute: float
    clock: Callable[[], float]

    def remaining_ms(self) -> int:
        return int((self.absolute - self.clock()) * 1000)

    def timeout(self, configured: int) -> int:
        remaining = self.remaining_ms()
        if remaining <= 0:
            raise _fail(FailureClass.MCP_TIMEOUT, "overall deadline expired")
        return min(configured, remaining)


@dataclass(frozen=True)
class ToolSurface:
    tools: tuple[AdvertisedTool, ...]
    identity: str
    output_schemas: Mapping[str, Mapping[str, Any] | None]


@dataclass(frozen=True)
class AuthorizedMcpAction:
    surface_identity: str
    action_id: LocalActionIdentity
    proposal_id: str
    name: str
    arguments: Mapping[str, Any]
    argument_bytes: bytes
    _issuer: object | None = field(default=None, init=False, repr=False, compare=False)


@dataclass(frozen=True)
class CorrelatedMcpResponse:
    request_id: int
    action_id: LocalActionIdentity | None
    result: Mapping[str, Any]
    byte_count: int
    provenance: EvidenceProvenance = EvidenceProvenance.VALIDATED_MCP_EVIDENCE


@dataclass(frozen=True)
class Evidence:
    action_id: LocalActionIdentity
    response_id: int
    result: Mapping[str, Any]
    provenance: EvidenceProvenance = EvidenceProvenance.VALIDATED_MCP_EVIDENCE


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class CancellationToken:
    """Project-owned cancellation source for the offline orchestration path."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


class ProviderTurn(Protocol):
    def turn(
        self,
        request: ProviderRequest,
        evidence: tuple[Evidence, ...],
        *,
        timeout_ms: int,
        cancellation: Cancellation | None,
    ) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]: ...


class BoundedProvider:
    """Project-owned marker for the small, bounded provider authority surface.

    The orchestrator intentionally does not accept structural ``.turn``
    lookalikes.  New providers must inherit this local marker and retain the
    same result and deadline contract as the deterministic provider below.
    """

    def turn(
        self,
        request: ProviderRequest,
        evidence: tuple[Evidence, ...],
        *,
        timeout_ms: int,
        cancellation: Cancellation | None,
    ) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]:
        raise NotImplementedError


@dataclass
class ScriptedProvider(BoundedProvider):
    """The only bounded orchestration provider double; it never outlives its budget."""

    responses: tuple[ProviderFinalMessage | Sequence[ProviderToolCallProposal], ...]
    delay_ms: int = 0
    _index: int = 0

    def turn(
        self,
        request: ProviderRequest,
        evidence: tuple[Evidence, ...],
        *,
        timeout_ms: int,
        cancellation: Cancellation | None,
    ) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]:
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise _fail(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider deadline")
        end = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < end and self.delay_ms > 0:
            if cancellation is not None and cancellation.is_set():
                raise _fail(FailureClass.CANCELLED, "provider cancelled")
            time.sleep(min(0.005, max(0, end - time.monotonic())))
            self.delay_ms -= 5
        if cancellation is not None and cancellation.is_set():
            raise _fail(FailureClass.CANCELLED, "provider cancelled")
        if self.delay_ms > 0 or time.monotonic() >= end:
            raise _fail(FailureClass.TOTAL_REQUEST_TIMEOUT, "provider timed out")
        if self._index >= len(self.responses):
            raise _fail(FailureClass.PERMANENT_PROVIDER_FAILURE, "script exhausted")
        result = self.responses[self._index]
        self._index += 1
        return result


def capture_tool_surface(result: Any, limits: Limits = DEFAULT_LIMITS) -> ToolSurface:
    tools = _closed(result, {"tools"}, {"tools"})["tools"]
    if not isinstance(tools, (list, tuple)) or len(tools) > limits.advertised_tool_count:
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool count invalid")
    captured: list[AdvertisedTool] = []
    canonical: list[Mapping[str, Any]] = []
    output_schemas: dict[str, Mapping[str, Any] | None] = {}
    for raw in tools:
        item = _closed(raw, _TOOL_FIELDS, {"name", "inputSchema"})
        if (
            not isinstance(item["name"], str)
            or not isinstance(item.get("title", ""), str)
            or not isinstance(item.get("description", ""), str)
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool definition text is invalid")
        for field_name in ("inputSchema", "outputSchema", "annotations", "execution", "_meta"):
            if field_name in item and not isinstance(item[field_name], dict):
                raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool definition object is invalid")
        if "icons" in item and not isinstance(item["icons"], (list, tuple)):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool icons are invalid")
        try:
            normalized_input = _normalize_input_schema(item["inputSchema"], limits)
            advertised = AdvertisedTool(item["name"], normalized_input, item.get("description", ""))
            provider_definition = {
                "name": advertised.name,
                "description": advertised.description,
                "inputSchema": advertised.parameters,
            }
            if len(_canon(provider_definition)) > limits.tool_definition_bytes:
                raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool definition invalid")
            output_schema = (
                _validate_output_schema_definition(item["outputSchema"], limits)
                if "outputSchema" in item
                else None
            )
            frozen_item = _freeze_json(item, limits=limits)
            if not isinstance(frozen_item, dict):
                raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool definition invalid")
        except ProviderError:
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool schema invalid") from None
        captured.append(advertised)
        canonical.append(frozen_item)
        output_schemas[advertised.name] = output_schema
    if len({x.name for x in captured}) != len(captured):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "duplicate tool")
    frozen_outputs = _freeze_json(output_schemas, limits=limits)
    if not isinstance(frozen_outputs, dict):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool output schemas are invalid")
    return ToolSurface(
        tuple(captured), hashlib.sha256(_canon(canonical)).hexdigest(), frozen_outputs
    )


def _tools_list_page(result: Any, limits: Limits) -> tuple[Sequence[Any], str | None]:
    page = _closed(result, {"tools", "nextCursor", "_meta"}, {"tools"})
    tools = page["tools"]
    if not isinstance(tools, (list, tuple)):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool list is invalid")
    if "_meta" in page:
        metadata = _freeze_json(page["_meta"], limits=limits)
        if not isinstance(metadata, dict):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool list metadata is invalid")
    cursor = page.get("nextCursor")
    if cursor is not None:
        if (
            not isinstance(cursor, str)
            or not cursor
            or len(cursor.encode("utf-8")) > limits.message_bytes
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool list cursor is invalid")
    return tools, cursor


class McpStdioClient:
    """One child and exactly one outstanding JSON-RPC request."""

    def __init__(
        self,
        executable: str,
        arguments: Sequence[str] = (),
        *,
        child_allowlist: Sequence[str] = (),
        parent_environment: Mapping[str, str] | None = None,
        limits: Limits = DEFAULT_LIMITS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            not isinstance(executable, str)
            or not executable
            or any(not isinstance(x, str) for x in arguments)
        ):
            raise _fail(FailureClass.INVALID_PROVIDER_CONFIGURATION, "bad child command")
        self.executable, self.arguments, self.limits, self.clock = (
            executable,
            tuple(arguments),
            limits,
            clock,
        )
        self.environment = build_child_environment(
            dict(os.environ if parent_environment is None else parent_environment),
            list(child_allowlist),
            provider_child=False,
        )
        self.process: subprocess.Popen[bytes] | None = None
        self.selector: selectors.BaseSelector | None = None
        self.surface: ToolSurface | None = None
        self.out = bytearray()
        self.err = bytearray()
        self.out_total = 0
        self.err_total = 0
        self.next_id = 1
        self._issuer = object()
        self._authorizations: dict[
            int, tuple[str, LocalActionIdentity, str, str, Mapping[str, Any], bytes]
        ] = {}
        self._startup_pending = True
        self.last_initialize: CorrelatedMcpResponse | None = None
        self.last_tools_list: CorrelatedMcpResponse | None = None

    def authorize(
        self,
        action_id: LocalActionIdentity,
        proposal_id: str,
        name: str,
        arguments: Mapping[str, Any],
    ) -> AuthorizedMcpAction:
        if self.surface is None:
            raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "surface absent")
        frozen = _freeze_json(arguments, limits=self.limits)
        if not isinstance(frozen, dict):
            raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "arguments invalid")
        tool = next((x for x in self.surface.tools if x.name == name), None)
        if tool is None:
            raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "tool unauthorized")
        _validate_schema(frozen, tool.parameters, self.limits)
        value = AuthorizedMcpAction(
            self.surface.identity, action_id, proposal_id, name, frozen, _canon(frozen)
        )
        object.__setattr__(value, "_issuer", self._issuer)
        self._authorizations[id(value)] = (
            value.surface_identity,
            value.action_id,
            value.proposal_id,
            value.name,
            value.arguments,
            value.argument_bytes,
        )
        return value

    def start(self, deadline: Deadline) -> None:
        if self.process is not None:
            raise _fail(FailureClass.LOCAL_POLICY_FAILURE, "child already started")
        deadline.timeout(self.limits.process_startup_timeout_ms)
        try:
            self.process = subprocess.Popen(
                [self.executable, *self.arguments],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.environment,
                shell=False,
                close_fds=True,
            )
            assert self.process.stdout and self.process.stderr
            os.set_blocking(self.process.stdout.fileno(), False)
            os.set_blocking(self.process.stderr.fileno(), False)
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ, "out")
            self.selector.register(self.process.stderr, selectors.EVENT_READ, "err")
            deadline.timeout(self.limits.process_startup_timeout_ms)
        except (OSError, ValueError, ProviderError):
            self.close(deadline, suppress=True)
            raise _fail(FailureClass.MCP_PROCESS_EXIT, "startup failed") from None

    def _drain(self, timeout: float, response_limit: int) -> list[bytes]:
        if self.process is None or self.selector is None:
            raise _fail(FailureClass.LOCAL_POLICY_FAILURE, "child unavailable")
        records = []
        for key, _ in self.selector.select(max(0, timeout)):
            try:
                data = os.read(key.fileobj.fileno(), 8192)
            except BlockingIOError:
                continue
            if not data:
                continue
            if key.data == "out":
                self.out_total += len(data)
                target, bound, total = self.out, self.limits.child_stdout_bytes, self.out_total
            else:
                self.err_total += len(data)
                target, bound, total = self.err, self.limits.child_stderr_bytes, self.err_total
            # stderr is never a protocol surface.  Retain only a fixed marker
            # for diagnostics so hostile child output cannot become a
            # project-owned secret-bearing buffer.
            target.extend(data if key.data == "out" else b"<redacted>")
            if total > bound:
                raise _fail(FailureClass.OVERSIZED_RESPONSE, "child output limit")
            if key.data == "out":
                while b"\n" in self.out:
                    line, _, rest = self.out.partition(b"\n")
                    self.out[:] = rest
                    if len(line) > response_limit:
                        raise _fail(FailureClass.OVERSIZED_RESPONSE, "response limit")
                    records.append(bytes(line))
                if len(self.out) > response_limit:
                    raise _fail(FailureClass.OVERSIZED_RESPONSE, "response limit")
        return records

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        deadline: Deadline,
        operation_ms: int,
        action: LocalActionIdentity | None = None,
        cancellation: Cancellation | None = None,
    ) -> CorrelatedMcpResponse:
        if method not in {"initialize", "tools/list", "tools/call"}:
            raise _fail(FailureClass.LOCAL_POLICY_FAILURE, "method rejected")
        if self.process is None:
            self.start(deadline)
        assert self.process and self.process.stdin
        # Popen is a trusted local primitive and cannot be safely preempted by
        # the standard library.  Its earliest enforceable readiness boundary is
        # the first initialize response, which is therefore also startup-bound.
        configured = (
            min(operation_ms, self.limits.process_startup_timeout_ms)
            if self._startup_pending
            else operation_ms
        )
        timeout_ms = deadline.timeout(configured)
        request_id = self.next_id
        self.next_id += 1
        response_limit = (
            self.limits.mcp_evidence_response_bytes
            if method == "tools/call"
            else self.limits.mcp_response_bytes
        )
        response_string_limit = (
            self.limits.mcp_evidence_response_bytes
            if method == "tools/call"
            else max(
                self.limits.message_bytes,
                self.limits.tool_argument_bytes,
                self.limits.tool_definition_bytes,
            )
        )
        raw = (
            _canon({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + b"\n"
        )
        if len(raw) > self.limits.mcp_request_bytes:
            raise _fail(FailureClass.REQUEST_TOO_LARGE, "request limit")
        try:
            self.process.stdin.write(raw)
            self.process.stdin.flush()
        except (OSError, BrokenPipeError):
            raise _fail(
                FailureClass.MCP_AMBIGUOUS_COMPLETION, "request transmission ambiguous"
            ) from None
        stop = self.clock() + timeout_ms / 1000
        while True:
            if cancellation is not None and cancellation.is_set():
                raise _fail(FailureClass.CANCELLED, "cancelled")
            if self.process.poll() is not None:
                if self.out:
                    raise _fail(FailureClass.TRUNCATED_RESPONSE, "incomplete stdout response")
                raise _fail(FailureClass.MCP_AMBIGUOUS_COMPLETION, "child exited after request")
            # Poll cancellation at a bounded cadence instead of sleeping through
            # a full request timeout.
            remaining = min(stop - self.clock(), deadline.timeout(operation_ms) / 1000, 0.01)
            if remaining <= 0:
                raise _fail(FailureClass.MCP_TIMEOUT, "response deadline")
            for line in self._drain(remaining, response_limit):
                mcp_limits = _mcp_evidence_limits(self.limits)
                try:
                    msg = parse_closed_json(
                        line,
                        mcp_limits,
                        byte_limit=response_limit,
                        string_bytes=response_string_limit,
                    )
                except ProviderError as exc:
                    raise _fail(exc.failure.classification, "invalid MCP JSON") from None
                obj = _closed(msg, {"jsonrpc", "id", "result", "error"}, {"jsonrpc", "id"})
                if (
                    obj.get("jsonrpc") != "2.0"
                    or type(obj.get("id")) is not int
                    or obj["id"] != request_id
                ):
                    raise _fail(
                        FailureClass.MCP_PROTOCOL_FAILURE, "unsolicited or wrong response ID"
                    )
                if ("result" in obj) == ("error" in obj):
                    raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "bad response shape")
                if "error" in obj:
                    err = _closed(obj["error"], {"code", "message", "data"}, {"code", "message"})
                    if type(err["code"]) is not int or not isinstance(err["message"], str):
                        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "bad error")
                    raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "MCP error")
                response = CorrelatedMcpResponse(
                    request_id,
                    action,
                    _freeze_json(
                        obj["result"],
                        limits=mcp_limits,
                        string_bytes=response_string_limit,
                    ),
                    len(line),
                )
                if method == "initialize":
                    self._startup_pending = False
                return response

    def _list_and_capture(
        self, deadline: Deadline, cancellation: Cancellation | None = None
    ) -> ToolSurface:
        collected: list[Any] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        while True:
            params: Mapping[str, Any] = {} if cursor is None else {"cursor": cursor}
            listed = self._request(
                "tools/list",
                params,
                deadline,
                self.limits.mcp_tools_list_timeout_ms,
                cancellation=cancellation,
            )
            self.last_tools_list = listed
            tools, next_cursor = _tools_list_page(listed.result, self.limits)
            if len(collected) + len(tools) > self.limits.advertised_tool_count:
                raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool count invalid")
            collected.extend(tools)
            if next_cursor is None:
                return capture_tool_surface({"tools": collected}, self.limits)
            if next_cursor in seen_cursors or not tools:
                raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool list pagination is invalid")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def initialize_and_capture(
        self, deadline: Deadline, cancellation: Cancellation | None = None
    ) -> ToolSurface:
        init = self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "native-mcp-agent", "version": MCP_CLIENT_VERSION},
            },
            deadline,
            self.limits.mcp_initialize_timeout_ms,
            cancellation=cancellation,
        )
        self.last_initialize = init
        value = _closed(
            init.result,
            {"protocolVersion", "capabilities", "serverInfo", "instructions", "_meta"},
            {"protocolVersion", "capabilities", "serverInfo"},
        )
        if (
            value["protocolVersion"] != MCP_PROTOCOL_VERSION
            or not isinstance(value["capabilities"], dict)
            or not isinstance(value["serverInfo"], dict)
            or ("_meta" in value and not isinstance(value["_meta"], dict))
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "bad initialize")
        assert self.process and self.process.stdin
        deadline.timeout(self.limits.mcp_initialize_timeout_ms)
        try:
            self.process.stdin.write(
                _canon({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                + b"\n"
            )
            self.process.stdin.flush()
        except (OSError, BrokenPipeError):
            raise _fail(
                FailureClass.MCP_AMBIGUOUS_COMPLETION, "initialized notification failed"
            ) from None
        self.surface = self._list_and_capture(deadline, cancellation)
        return self.surface

    def revalidate_surface(
        self, deadline: Deadline, cancellation: Cancellation | None = None
    ) -> None:
        if self.surface is None:
            raise _fail(FailureClass.LOCAL_POLICY_FAILURE, "surface absent")
        later = self._list_and_capture(deadline, cancellation)
        if later.identity != self.surface.identity:
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool surface changed")

    def execute(
        self,
        action: AuthorizedMcpAction,
        deadline: Deadline,
        cancellation: Cancellation | None = None,
    ) -> CorrelatedMcpResponse:
        expected = self._authorizations.get(id(action))
        actual = (
            (
                action.surface_identity,
                action.action_id,
                action.proposal_id,
                action.name,
                action.arguments,
                action.argument_bytes,
            )
            if isinstance(action, AuthorizedMcpAction)
            else None
        )
        if (
            not isinstance(action, AuthorizedMcpAction)
            or action._issuer is not self._issuer
            or self.surface is None
            or action.surface_identity != self.surface.identity
            or expected != actual
        ):
            raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "forged or stale authorization")
        tool = next((x for x in self.surface.tools if x.name == action.name), None)
        if tool is None or not isinstance(action.action_id, LocalActionIdentity):
            raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "tool unauthorized")
        try:
            frozen = _freeze_json(action.arguments, limits=self.limits)
            _validate_schema(frozen, tool.parameters, self.limits)
        except ProviderError:
            raise _fail(
                FailureClass.LOCAL_AUTHORIZATION_FAILURE, "arguments unauthorized"
            ) from None
        if (
            not isinstance(frozen, dict)
            or _canon(frozen) != action.argument_bytes
            or len(action.argument_bytes) > self.limits.tool_argument_bytes
        ):
            raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE, "arguments changed")
        response = self._request(
            "tools/call",
            {"name": action.name, "arguments": frozen},
            deadline,
            self.limits.mcp_call_timeout_ms,
            action,
            cancellation,
        )
        output_schema = self.surface.output_schemas.get(action.name)
        return CorrelatedMcpResponse(
            response.request_id,
            action.action_id,
            _validate_tool_result(response.result, self.limits, output_schema),
            response.byte_count,
        )

    def close(self, deadline: Deadline | None = None, *, suppress: bool = False) -> str:
        process = self.process
        if process is None:
            return "none"
        mode = "none"
        try:
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                mode = "terminate"
                process.terminate()
                # Every blocking wait under orchestration ownership consumes
                # only a positive slice of its absolute deadline.  Once it is
                # exhausted, signals and poll() are safe but wait() is not.
                graceful_wait = (
                    min(self.limits.graceful_shutdown_timeout_ms, deadline.remaining_ms()) / 1000
                    if deadline and deadline.remaining_ms() > 0
                    else self.limits.graceful_shutdown_timeout_ms / 1000
                    if deadline is None
                    else None
                )
                if graceful_wait is not None:
                    try:
                        process.wait(graceful_wait)
                    except subprocess.TimeoutExpired:
                        pass
            if process.poll() is None:
                mode = "kill"
                process.kill()
                reap_wait = (
                    deadline.remaining_ms() / 1000
                    if deadline and deadline.remaining_ms() > 0
                    else 0.2
                    if deadline is None
                    else None
                )
                if reap_wait is not None:
                    try:
                        process.wait(reap_wait)
                    except subprocess.TimeoutExpired:
                        pass
                else:
                    # timeout=0 is a non-blocking reap attempt, not a new
                    # lease after the orchestration deadline.
                    try:
                        process.wait(0)
                    except subprocess.TimeoutExpired:
                        pass
            if process.poll() is None:
                mode = "unreaped"
                if not suppress:
                    raise _fail(
                        FailureClass.MCP_PROCESS_EXIT, "child unreaped at shutdown deadline"
                    )
        except (OSError, BrokenPipeError):
            mode = "unreaped"
            if not suppress:
                raise _fail(FailureClass.MCP_PROCESS_EXIT, "shutdown failed") from None
        finally:
            if self.selector:
                self.selector.close()
            for stream in (process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except OSError:
                    pass
            self.selector = None
            self.process = None
        return mode


def _validate_tool_result(
    value: Any, limits: Limits, output_schema: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    mcp_limits = _mcp_evidence_limits(limits)
    obj = _closed(value, {"content", "structuredContent", "isError", "_meta"}, {"content"})
    is_error = obj.get("isError", False)
    if (
        not isinstance(obj["content"], (list, tuple))
        or len(obj["content"]) > limits.object_array_items
        or type(is_error) is not bool
    ):
        raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "bad tool result")
    if "_meta" in obj:
        metadata = _freeze_json(
            obj["_meta"], limits=mcp_limits, string_bytes=limits.mcp_evidence_response_bytes
        )
        if not isinstance(metadata, dict):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "bad tool result metadata")
    blocks = []
    for block in obj["content"]:
        item = _closed(block, {"type", "text"}, {"type", "text"})
        if (
            item["type"] != "text"
            or not isinstance(item["text"], str)
            or len(item["text"].encode()) > limits.mcp_evidence_response_bytes
        ):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "unsupported content")
        blocks.append({"type": "text", "text": redact_json({"message": item["text"]})["message"]})
    output = {"content": blocks}
    if "isError" in obj:
        output["isError"] = is_error
    if "structuredContent" in obj:
        structured = _freeze_json(
            obj["structuredContent"],
            limits=mcp_limits,
            string_bytes=limits.mcp_evidence_response_bytes,
        )
        if not isinstance(structured, dict):
            raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "structured content must be an object")
        if output_schema is not None and not is_error:
            _validate_output_value(structured, output_schema, limits)
        output["structuredContent"] = redact_json(structured)
    elif output_schema is not None and not is_error:
        raise _fail(
            FailureClass.MCP_PROTOCOL_FAILURE, "structured content is required by the output schema"
        )
    return _freeze_json(output, limits=mcp_limits, string_bytes=limits.mcp_evidence_response_bytes)


@dataclass(frozen=True)
class OrchestrationOutcome:
    outcome: str
    evidence: tuple[Evidence, ...]
    execution_order: tuple[LocalActionIdentity, ...]
    transcript: bytes


class Orchestrator:
    def __init__(
        self,
        client: McpStdioClient,
        provider: ProviderTurn,
        *,
        limits: Limits = DEFAULT_LIMITS,
        context: str = "offline",
        clock: Callable[[], float] = time.monotonic,
        cancellation: Cancellation | None = None,
    ) -> None:
        # bounded orchestration deliberately supports only the project-owned deterministic
        # double.  A future live adapter needs a separate authority decision.
        if not isinstance(provider, BoundedProvider):
            raise _fail(
                FailureClass.LOCAL_POLICY_FAILURE, "unbounded provider implementation rejected"
            )
        self.client, self.provider, self.limits, self.context, self.clock, self.cancellation = (
            client,
            provider,
            limits,
            context,
            clock,
            cancellation,
        )
        self.actions: set[str] = set()
        self.call_ids: dict[str, bytes] = {}
        self.evidence: list[Evidence] = []
        self.order: list[LocalActionIdentity] = []
        self.transcript = BoundedTranscript(limits)
        self._deadline: Deadline | None = None

    def _action(self, p: ProviderToolCallProposal, surface: ToolSurface) -> LocalActionIdentity:
        return LocalActionIdentity(
            hashlib.sha256(
                _canon(
                    {
                        "surface": surface.identity,
                        "name": p.name,
                        "arguments": p.arguments,
                        "context": self.context,
                    }
                )
            ).hexdigest()[:32]
        )

    def _outcome(self, outcome: str) -> OrchestrationOutcome:
        # Serialize shutdown control evidence before the immutable transcript.
        self.transcript.add("shutdown_start")
        mode = self.client.close(self._deadline, suppress=True)
        if mode == "terminate":
            self.transcript.add("shutdown_terminate")
        elif mode == "kill":
            self.transcript.add("shutdown_terminate")
            self.transcript.add("shutdown_kill")
        elif mode == "unreaped":
            self.transcript.add("shutdown_terminate")
            self.transcript.add("shutdown_kill")
            self.transcript.add("shutdown_unreaped")
        if mode != "unreaped":
            self.transcript.add("shutdown_complete")
        self.transcript.add("outcome", outcome=outcome)
        raw = self.transcript.to_json_bytes()
        parse_bounded_transcript(raw, self.limits)
        return OrchestrationOutcome(outcome, tuple(self.evidence), tuple(self.order), raw)

    def run(self, request: ProviderRequest) -> OrchestrationOutcome:
        deadline = Deadline(
            self.clock() + self.limits.orchestration_total_timeout_ms / 1000, self.clock
        )
        self._deadline = deadline
        try:
            self.transcript.add("process_start")
            self.transcript.add("initialize_request")
            surface = self.client.initialize_and_capture(deadline, self.cancellation)
            self.transcript.add(
                "initialize_response",
                response=str(
                    self.client.last_initialize.request_id if self.client.last_initialize else 1
                ),
            )
            self.transcript.add("initialized_notification")
            self.transcript.add("tools_list_request")
            self.transcript.add(
                "tools_list_response",
                response=str(
                    self.client.last_tools_list.request_id if self.client.last_tools_list else 2
                ),
            )
            self.transcript.add("surface_captured", surface=surface.identity)
            for turn in range(self.limits.provider_turn_count):
                if self.cancellation and self.cancellation.is_set():
                    return self._outcome("cancelled")
                timeout = deadline.timeout(self.limits.provider_total_timeout_ms)
                bounded = ProviderRequest(
                    request.model,
                    request.messages,
                    surface.tools,
                    request.max_output_tokens,
                    request.correlation_id,
                    request.generation,
                )
                raw = bounded.to_json_bytes(self.limits)
                self.transcript.add("provider_turn_start", turn=str(turn), bytes=str(len(raw)))
                response = self.provider.turn(
                    bounded,
                    tuple(self.evidence),
                    timeout_ms=timeout,
                    cancellation=self.cancellation,
                )
                if deadline.remaining_ms() <= 0:
                    return self._outcome("deadline")
                try:
                    encoded_response = _canon(_provider_response_value(response))
                except (TypeError, ValueError, ProviderError):
                    return self._outcome("failed")
                if len(encoded_response) > self.limits.provider_response_bytes:
                    return self._outcome("failed")
                self.transcript.add(
                    "provider_turn_response", turn=str(turn), bytes=str(len(encoded_response))
                )
                if isinstance(response, ProviderFinalMessage):
                    return self._outcome("final")
                proposals = tuple(response)
                if (
                    len(proposals) > self.limits.proposed_tool_call_count
                    or len(proposals) > self.limits.mcp_calls_per_turn
                ):
                    return self._outcome("rejected")
                prepared = []
                for proposal_index, p in enumerate(proposals):
                    if not isinstance(p, ProviderToolCallProposal):
                        self.transcript.add("proposal_rejected", proposal="invalid")
                        return self._outcome("rejected")
                    tool = next((x for x in surface.tools if x.name == p.name), None)
                    if tool is None:
                        self.transcript.add("proposal_rejected", proposal=str(p.call_id))
                        return self._outcome("rejected")
                    try:
                        frozen = _freeze_json(p.arguments, limits=self.limits)
                        _validate_schema(frozen, tool.parameters, self.limits)
                    except ProviderError:
                        # Proposal validation is a serial authority boundary: a
                        # locally rejected first proposal ends this provider
                        # turn before any later proposal can be authorized or
                        # consume a JSON-RPC tools/call request ID.
                        self.transcript.add("proposal_rejected", proposal=str(p.call_id))
                        for later in proposals[proposal_index + 1 :]:
                            if isinstance(later, ProviderToolCallProposal):
                                self.transcript.add("skipped", proposal=str(later.call_id))
                        return self._outcome("rejected")
                    content = _canon({"name": p.name, "arguments": frozen})
                    aid = self._action(p, surface)
                    if (
                        str(p.call_id) in self.call_ids
                        or aid.value in self.actions
                        or any(
                            str(x[0].call_id) == str(p.call_id) or x[1].value == aid.value
                            for x in prepared
                        )
                    ):
                        self.transcript.add("proposal_duplicate", proposal=str(p.call_id))
                        return self._outcome("duplicate")
                    prepared.append((p, aid, content, frozen))
                for index, (p, aid, content, frozen) in enumerate(prepared):
                    if self.cancellation and self.cancellation.is_set():
                        self.transcript.add("cancelled")
                        self.transcript.add("skipped", proposal=str(p.call_id))
                        return self._outcome("cancelled")
                    if (
                        len(self.order) >= self.limits.mcp_total_calls
                        or deadline.remaining_ms() <= 0
                    ):
                        self.transcript.add("deadline")
                        self.transcript.add("skipped", proposal=str(p.call_id))
                        return self._outcome("deadline")
                    auth = self.client.authorize(aid, str(p.call_id), p.name, frozen)
                    self.call_ids[str(p.call_id)] = content
                    self.actions.add(aid.value)
                    self.transcript.add("authorized", action=aid.value, proposal=str(p.call_id))
                    try:
                        self.transcript.add(
                            "mcp_request", action=aid.value, response=str(self.client.next_id)
                        )
                        response = self.client.execute(auth, deadline, self.cancellation)
                        self.order.append(aid)
                        self.evidence.append(Evidence(aid, response.request_id, response.result))
                        self.transcript.add(
                            "mcp_response", action=aid.value, response=str(response.request_id)
                        )
                        self.transcript.add(
                            "evidence_validated",
                            action=aid.value,
                            response=str(response.request_id),
                        )
                    except ProviderError as exc:
                        self.transcript.add("failure", failure=exc.failure.classification.value)
                        for later, *_ in prepared[index + 1 :]:
                            self.transcript.add("skipped", proposal=str(later.call_id))
                        return self._outcome(
                            "cancelled"
                            if exc.failure.classification is FailureClass.CANCELLED
                            else "failed"
                        )
            return self._outcome("budget")
        except ProviderError as exc:
            if exc.failure.classification is FailureClass.CANCELLED:
                self.transcript.add("cancelled")
                return self._outcome("cancelled")
            timed_out = exc.failure.classification in {
                FailureClass.MCP_TIMEOUT,
                FailureClass.TOTAL_REQUEST_TIMEOUT,
            }
            self.transcript.add(
                "deadline" if timed_out else "failure",
                **({} if timed_out else {"failure": exc.failure.classification.value}),
            )
            return self._outcome("deadline" if timed_out else "failed")
        finally:
            self.client.close(deadline, suppress=True)


def _provider_response_value(
    response: ProviderFinalMessage | Sequence[ProviderToolCallProposal],
) -> Mapping[str, Any]:
    """Canonical bounded orchestration provider response representation."""
    if isinstance(response, ProviderFinalMessage):
        return {
            "kind": "final",
            "role": response.message.role.value,
            "content": response.message.content,
        }
    calls = []
    for proposal in response:
        if not isinstance(proposal, ProviderToolCallProposal):
            raise _fail(FailureClass.INVALID_TOOL_PROPOSAL, "provider response invalid")
        calls.append(
            {"id": str(proposal.call_id), "name": proposal.name, "arguments": proposal.arguments}
        )
    return {"kind": "proposals", "calls": calls}
