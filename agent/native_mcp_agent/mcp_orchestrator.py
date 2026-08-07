"""Offline, serial, bounded MCP stdio orchestration.

This is deliberately a small JSON-RPC client, not a general MCP transport.
Only the three locally constructed methods below can cross this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import selectors
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

from .contracts import (AdvertisedTool, EvidenceProvenance, LocalActionIdentity,
    ProviderFinalMessage, ProviderRequest, ProviderToolCallProposal,
    RequestCorrelationId, _freeze_json, _validate_schema, parse_closed_json)
from .environment import build_child_environment
from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, Limits


class McpError(ProviderError):
    pass


def _err(kind: FailureClass, detail: str) -> McpError:
    return McpError(failure(kind, detail))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _closed(value: Any, allowed: set[str], required: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise _err(FailureClass.MCP_PROTOCOL_FAILURE, label)
    return value


def _jsonrpc_response(value: Any, request_id: int) -> Mapping[str, Any]:
    obj = _closed(value, {"jsonrpc", "id", "result", "error"}, {"jsonrpc", "id"}, "response is not closed")
    if obj["jsonrpc"] != "2.0" or type(obj["id"]) is not int or obj["id"] != request_id:
        raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "response correlation is invalid")
    if ("result" in obj) == ("error" in obj):
        raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "response result/error shape is invalid")
    if "error" in obj:
        error = _closed(obj["error"], {"code", "message", "data"}, {"code", "message"}, "MCP error is malformed")
        if type(error["code"]) is not int or not isinstance(error["message"], str):
            raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "MCP error is malformed")
        raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "MCP returned an error")
    return obj


@dataclass(frozen=True)
class ToolSurface:
    tools: tuple[AdvertisedTool, ...]
    identity: str


def capture_tool_surface(result: Any, limits: Limits = DEFAULT_LIMITS) -> ToolSurface:
    obj = _closed(result, {"tools"}, {"tools"}, "tools/list result is not closed")
    tools = obj["tools"]
    if not isinstance(tools, list) or len(tools) > limits.advertised_tool_count:
        raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "tool count is invalid")
    captured: list[AdvertisedTool] = []
    for raw in tools:
        item = _closed(raw, {"name", "description", "inputSchema"}, {"name", "inputSchema"}, "tool definition is not closed")
        if not isinstance(item["name"], str) or not isinstance(item.get("description", ""), str):
            raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "tool definition fields are invalid")
        try:
            definition = _canonical(item)
            if len(definition) > limits.tool_definition_bytes:
                raise ValueError
            captured.append(AdvertisedTool(item["name"], item["inputSchema"], item.get("description", "")))
        except (ProviderError, TypeError, ValueError, UnicodeError):
            raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "tool schema is invalid") from None
    if len({tool.name for tool in captured}) != len(captured):
        raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "duplicate advertised tool")
    canonical = [{"name": t.name, "description": t.description, "inputSchema": t.parameters} for t in captured]
    return ToolSurface(tuple(captured), hashlib.sha256(_canonical(canonical)).hexdigest())


class McpStdioClient:
    """One child, one outstanding request.  Its IDs are local monotonically IDs."""
    def __init__(self, executable: str, arguments: Sequence[str] = (), *, child_allowlist: Sequence[str] = (),
                 parent_environment: Mapping[str, str] | None = None, limits: Limits = DEFAULT_LIMITS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(executable, str) or not executable or any(not isinstance(x, str) for x in arguments):
            raise _err(FailureClass.INVALID_PROVIDER_CONFIGURATION, "trusted child command is invalid")
        self.executable, self.arguments, self.limits, self.clock = executable, tuple(arguments), limits, clock
        self.environment = build_child_environment(dict(os.environ if parent_environment is None else parent_environment), list(child_allowlist), provider_child=False)
        self.process: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._stdout = bytearray(); self._stderr = bytearray(); self._stdout_total = 0; self._stderr_total = 0; self._next_id = 1
        self.surface: ToolSurface | None = None

    def start(self) -> None:
        if self.process is not None:
            raise _err(FailureClass.LOCAL_POLICY_FAILURE, "child already started")
        try:
            self.process = subprocess.Popen([self.executable, *self.arguments], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=self.environment, shell=False, close_fds=True)
            assert self.process.stdout and self.process.stderr
            os.set_blocking(self.process.stdout.fileno(), False); os.set_blocking(self.process.stderr.fileno(), False)
            self._selector = selectors.DefaultSelector(); self._selector.register(self.process.stdout, selectors.EVENT_READ, "out"); self._selector.register(self.process.stderr, selectors.EVENT_READ, "err")
        except (OSError, ValueError):
            raise _err(FailureClass.MCP_PROCESS_EXIT, "child could not start") from None

    def _drain(self, timeout: float) -> list[bytes]:
        if self.process is None or self._selector is None: raise _err(FailureClass.LOCAL_POLICY_FAILURE, "child is not running")
        records: list[bytes] = []
        for key, _ in self._selector.select(max(0.0, timeout)):
            try: data = os.read(key.fileobj.fileno(), 8192)
            except BlockingIOError: continue
            if not data: continue
            target, bound = (self._stdout, self.limits.child_stdout_bytes) if key.data == "out" else (self._stderr, self.limits.child_stderr_bytes)
            if key.data == "out": self._stdout_total += len(data); total = self._stdout_total
            else: self._stderr_total += len(data); total = self._stderr_total
            target.extend(data)
            if total > bound: raise _err(FailureClass.OVERSIZED_RESPONSE, "child output exceeds byte limit")
            if key.data == "out":
                while b"\n" in self._stdout:
                    line, _, remainder = self._stdout.partition(b"\n"); self._stdout[:] = remainder
                    if len(line) > self.limits.mcp_response_bytes: raise _err(FailureClass.OVERSIZED_RESPONSE, "MCP response exceeds byte limit")
                    records.append(bytes(line))
        return records

    def request(self, method: str, params: Mapping[str, Any], timeout_ms: int) -> Any:
        if method not in {"initialize", "tools/list", "tools/call"}: raise _err(FailureClass.LOCAL_POLICY_FAILURE, "MCP method is not locally authorized")
        if self.process is None: self.start()
        assert self.process and self.process.stdin
        request_id = self._next_id; self._next_id += 1
        raw = _canonical({"jsonrpc":"2.0", "id":request_id, "method":method, "params":params}) + b"\n"
        if len(raw) > self.limits.mcp_request_bytes: raise _err(FailureClass.REQUEST_TOO_LARGE, "MCP request exceeds byte limit")
        if self.process.poll() is not None: raise _err(FailureClass.MCP_PROCESS_EXIT, "child exited before request")
        try: self.process.stdin.write(raw); self.process.stdin.flush()
        except (BrokenPipeError, OSError): raise _err(FailureClass.MCP_AMBIGUOUS_COMPLETION, "MCP request transmission is ambiguous") from None
        deadline = self.clock() + timeout_ms / 1000.0
        while True:
            if self.process.poll() is not None: raise _err(FailureClass.MCP_AMBIGUOUS_COMPLETION, "child exited after request transmission")
            remain = deadline - self.clock()
            if remain <= 0: raise _err(FailureClass.MCP_TIMEOUT, "MCP response deadline elapsed")
            records = self._drain(remain)
            for line in records:
                try:
                    message = parse_closed_json(line, self.limits, byte_limit=self.limits.mcp_response_bytes)
                except ProviderError as exc:
                    raise _err(exc.failure.classification, "MCP JSON is invalid") from None
                response = _jsonrpc_response(message, request_id)
                result = response["result"]
                if method == "tools/list" and self.surface is not None and capture_tool_surface(result, self.limits).identity != self.surface.identity:
                    raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "advertised tool surface changed")
                return result

    def initialize_and_capture(self) -> ToolSurface:
        result = self.request("initialize", {"protocolVersion":"2024-11-05", "capabilities":{}, "clientInfo":{"name":"native-mcp-agent","version":"10.2"}}, self.limits.mcp_initialize_timeout_ms)
        obj = _closed(result, {"protocolVersion", "capabilities", "serverInfo", "instructions"}, {"protocolVersion", "capabilities", "serverInfo"}, "initialize result is malformed")
        if not isinstance(obj["protocolVersion"], str) or not isinstance(obj["capabilities"], dict) or not isinstance(obj["serverInfo"], dict): raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "initialize result is malformed")
        # Notification is intentionally not a request and is locally fixed.
        assert self.process and self.process.stdin
        self.process.stdin.write(_canonical({"jsonrpc":"2.0", "method":"notifications/initialized", "params":{}}) + b"\n"); self.process.stdin.flush()
        surface = capture_tool_surface(self.request("tools/list", {}, self.limits.mcp_tools_list_timeout_ms), self.limits)
        self.surface = surface
        return surface

    def call(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if self.surface is None: raise _err(FailureClass.LOCAL_POLICY_FAILURE, "tool surface has not been captured")
        return self.request("tools/call", {"name":name, "arguments":arguments}, self.limits.mcp_call_timeout_ms)

    def close(self) -> None:
        if self.process is None: return
        try:
            if self.process.stdin: self.process.stdin.close()
            self.process.terminate(); self.process.wait(self.limits.graceful_shutdown_timeout_ms / 1000.0)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait(1.0)
        finally:
            if self._selector: self._selector.close()
            for stream in (self.process.stdout, self.process.stderr):
                try:
                    if stream: stream.close()
                except OSError:
                    pass
            self.process = None


@dataclass(frozen=True)
class Evidence:
    action_id: LocalActionIdentity
    mcp_request_id: int
    result: Mapping[str, Any]
    provenance: EvidenceProvenance = EvidenceProvenance.VALIDATED_MCP_EVIDENCE

@dataclass(frozen=True)
class OrchestrationOutcome:
    outcome: str
    evidence: tuple[Evidence, ...]
    execution_order: tuple[LocalActionIdentity, ...]
    transcript: bytes

class Orchestrator:
    def __init__(self, client: McpStdioClient, *, limits: Limits = DEFAULT_LIMITS, context: str = "offline", clock: Callable[[], float] = time.monotonic) -> None:
        self.client, self.limits, self.context, self.clock = client, limits, context, clock
        self.call_ids: dict[str, bytes] = {}; self.actions: set[str] = set(); self.evidence: list[Evidence] = []; self.order: list[LocalActionIdentity] = []; self.events: list[dict[str, Any]] = []

    def _action(self, proposal: ProviderToolCallProposal, surface: ToolSurface) -> LocalActionIdentity:
        return LocalActionIdentity(hashlib.sha256(_canonical({"surface":surface.identity,"name":proposal.name,"arguments":proposal.arguments,"context":self.context})).hexdigest()[:32])

    def run(self, provider: Callable[[ProviderRequest, tuple[Evidence, ...]], ProviderFinalMessage | Sequence[ProviderToolCallProposal]], request: ProviderRequest) -> OrchestrationOutcome:
        deadline = self.clock() + self.limits.orchestration_total_timeout_ms / 1000.0
        surface = self.client.initialize_and_capture(); self.events.append({"event":"surface","identity":surface.identity})
        tools = surface.tools
        for turn in range(self.limits.provider_turn_count):
            if self.clock() >= deadline: return self._outcome("deadline")
            bounded = ProviderRequest(request.model, request.messages, tools, request.max_output_tokens, request.correlation_id, request.generation)
            response = provider(bounded, tuple(self.evidence))
            self.events.append({"event":"provider_turn","turn":turn,"id":str(request.correlation_id)})
            if isinstance(response, ProviderFinalMessage): return self._outcome("final")
            proposals = tuple(response)
            if len(proposals) > self.limits.proposed_tool_call_count or len(proposals) > self.limits.mcp_calls_per_turn: return self._outcome("rejected")
            # Validate the complete list before an action is authorized.
            prepared: list[tuple[ProviderToolCallProposal, LocalActionIdentity]] = []
            for proposal in proposals:
                if not isinstance(proposal, ProviderToolCallProposal) or proposal.name not in {x.name for x in tools}: return self._outcome("rejected")
                try: _validate_schema(proposal.arguments, next(x.parameters for x in tools if x.name == proposal.name), self.limits); frozen = _freeze_json(proposal.arguments, limits=self.limits)
                except ProviderError: return self._outcome("rejected")
                content = _canonical({"name":proposal.name,"arguments":frozen})
                prior = self.call_ids.get(str(proposal.call_id))
                action = self._action(proposal, surface)
                if prior is not None and prior != content or prior is not None or action.value in self.actions or any(a.value == action.value for _, a in prepared): return self._outcome("duplicate")
                self.call_ids[str(proposal.call_id)] = content; prepared.append((proposal, action))
            for proposal, action in prepared:
                if len(self.order) >= self.limits.mcp_total_calls or self.clock() >= deadline: return self._outcome("deadline")
                self.actions.add(action.value); self.events.append({"event":"authorized","action":action.value,"proposal":str(proposal.call_id)})
                try:
                    result = self.client.call(proposal.name, proposal.arguments)
                    # A tools/call result is deliberately accepted only as a closed object.
                    result_obj = _closed(result, {"content", "isError", "structuredContent"}, {"content"}, "tools/call result is malformed")
                    if not isinstance(result_obj["content"], list): raise _err(FailureClass.MCP_PROTOCOL_FAILURE, "tools/call result is malformed")
                    self.order.append(action); self.evidence.append(Evidence(action, self.client._next_id - 1, _freeze_json(result_obj, limits=self.limits)))
                except ProviderError as exc:
                    self.events.append({"event":"failed","action":action.value,"failure":exc.failure.classification.value}); return self._outcome("failed")
        return self._outcome("budget")

    def _outcome(self, outcome: str) -> OrchestrationOutcome:
        value = {"schemaVersion":1,"outcome":outcome,"events":self.events,"order":[x.value for x in self.order],"evidence":[{"action":x.action_id.value,"request":x.mcp_request_id} for x in self.evidence]}
        raw = _canonical(value)
        if len(raw) > self.limits.transcript_bytes: raw = _canonical({"schemaVersion":1,"outcome":"transcript_limit"})
        return OrchestrationOutcome(outcome, tuple(self.evidence), tuple(self.order), raw)
