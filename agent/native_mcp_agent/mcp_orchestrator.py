"""Closed, serial and deadline-bounded offline MCP orchestration."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib, json, os, selectors, subprocess, time
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contracts import (AdvertisedTool, EvidenceProvenance, LocalActionIdentity,
    ProviderFinalMessage, ProviderRequest, ProviderToolCallProposal, _freeze_json,
    _validate_schema, parse_closed_json)
from .environment import build_child_environment
from .errors import FailureClass, ProviderError, failure
from .limits import DEFAULT_LIMITS, Limits
from .redaction import redact_json
from .transcript import Phase10Transcript, parse_phase_10_2_transcript

class McpError(ProviderError): pass
def _fail(kind: FailureClass, detail: str) -> McpError: return McpError(failure(kind, detail))
def _canon(value: Any) -> bytes: return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
def _closed(value: Any, allowed: set[str], required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "closed schema rejected")
    return value

@dataclass(frozen=True)
class Deadline:
    absolute: float
    clock: Callable[[], float]
    def remaining_ms(self) -> int: return int((self.absolute - self.clock()) * 1000)
    def timeout(self, configured: int) -> int:
        remaining = self.remaining_ms()
        if remaining <= 0: raise _fail(FailureClass.MCP_TIMEOUT, "overall deadline expired")
        return min(configured, remaining)

@dataclass(frozen=True)
class ToolSurface:
    tools: tuple[AdvertisedTool, ...]
    identity: str

@dataclass(frozen=True)
class AuthorizedMcpAction:
    surface_identity: str
    action_id: LocalActionIdentity
    proposal_id: str
    name: str
    arguments: Mapping[str, Any]
    argument_bytes: bytes

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
class ProviderTurn(Protocol):
    def turn(self, request: ProviderRequest, evidence: tuple[Evidence, ...], *, timeout_ms: int, cancellation: Cancellation | None) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]: ...

def capture_tool_surface(result: Any, limits: Limits = DEFAULT_LIMITS) -> ToolSurface:
    tools = _closed(result, {"tools"}, {"tools"})["tools"]
    if not isinstance(tools, (list, tuple)) or len(tools) > limits.advertised_tool_count: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool count invalid")
    captured: list[AdvertisedTool] = []
    for raw in tools:
        item = _closed(raw, {"name", "description", "inputSchema"}, {"name", "inputSchema"})
        if not isinstance(item["name"], str) or not isinstance(item.get("description", ""), str) or len(_canon(item)) > limits.tool_definition_bytes: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool definition invalid")
        try: captured.append(AdvertisedTool(item["name"], item["inputSchema"], item.get("description", "")))
        except ProviderError: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "tool schema invalid") from None
    if len({x.name for x in captured}) != len(captured): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE, "duplicate tool")
    value = [{"name":x.name,"description":x.description,"inputSchema":x.parameters} for x in captured]
    return ToolSurface(tuple(captured), hashlib.sha256(_canon(value)).hexdigest())

class McpStdioClient:
    """One child and exactly one outstanding JSON-RPC request."""
    def __init__(self, executable: str, arguments: Sequence[str] = (), *, child_allowlist: Sequence[str] = (), parent_environment: Mapping[str,str] | None = None, limits: Limits = DEFAULT_LIMITS, clock: Callable[[],float] = time.monotonic) -> None:
        if not isinstance(executable,str) or not executable or any(not isinstance(x,str) for x in arguments): raise _fail(FailureClass.INVALID_PROVIDER_CONFIGURATION,"bad child command")
        self.executable,self.arguments,self.limits,self.clock=executable,tuple(arguments),limits,clock
        self.environment=build_child_environment(dict(os.environ if parent_environment is None else parent_environment),list(child_allowlist),provider_child=False)
        self.process: subprocess.Popen[bytes]|None=None; self.selector: selectors.BaseSelector|None=None; self.surface: ToolSurface|None=None
        self.out=bytearray(); self.err=bytearray(); self.out_total=0; self.err_total=0; self.next_id=1

    def start(self, deadline: Deadline) -> None:
        if self.process is not None: raise _fail(FailureClass.LOCAL_POLICY_FAILURE,"child already started")
        deadline.timeout(self.limits.process_startup_timeout_ms)
        try:
            self.process=subprocess.Popen([self.executable,*self.arguments],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=self.environment,shell=False,close_fds=True)
            assert self.process.stdout and self.process.stderr
            os.set_blocking(self.process.stdout.fileno(),False); os.set_blocking(self.process.stderr.fileno(),False)
            self.selector=selectors.DefaultSelector(); self.selector.register(self.process.stdout,selectors.EVENT_READ,"out"); self.selector.register(self.process.stderr,selectors.EVENT_READ,"err")
            deadline.timeout(self.limits.process_startup_timeout_ms)
        except (OSError,ValueError,ProviderError):
            self.close(deadline, suppress=True); raise _fail(FailureClass.MCP_PROCESS_EXIT,"startup failed") from None

    def _drain(self, timeout: float) -> list[bytes]:
        if self.process is None or self.selector is None: raise _fail(FailureClass.LOCAL_POLICY_FAILURE,"child unavailable")
        records=[]
        for key,_ in self.selector.select(max(0,timeout)):
            try: data=os.read(key.fileobj.fileno(),8192)
            except BlockingIOError: continue
            if not data: continue
            if key.data=="out": self.out_total+=len(data); target,bound,total=self.out,self.limits.child_stdout_bytes,self.out_total
            else: self.err_total+=len(data); target,bound,total=self.err,self.limits.child_stderr_bytes,self.err_total
            target.extend(data)
            if total>bound: raise _fail(FailureClass.OVERSIZED_RESPONSE,"child output limit")
            if key.data=="out":
                while b"\n" in self.out:
                    line,_,rest=self.out.partition(b"\n"); self.out[:]=rest
                    if len(line)>self.limits.mcp_response_bytes: raise _fail(FailureClass.OVERSIZED_RESPONSE,"response limit")
                    records.append(bytes(line))
        return records

    def _request(self, method: str, params: Mapping[str,Any], deadline: Deadline, operation_ms: int, action: LocalActionIdentity|None=None, cancellation: Cancellation|None=None) -> CorrelatedMcpResponse:
        if method not in {"initialize","tools/list","tools/call"}: raise _fail(FailureClass.LOCAL_POLICY_FAILURE,"method rejected")
        if self.process is None: self.start(deadline)
        assert self.process and self.process.stdin
        timeout_ms=deadline.timeout(operation_ms); request_id=self.next_id; self.next_id+=1
        raw=_canon({"jsonrpc":"2.0","id":request_id,"method":method,"params":params})+b"\n"
        if len(raw)>self.limits.mcp_request_bytes: raise _fail(FailureClass.REQUEST_TOO_LARGE,"request limit")
        try: self.process.stdin.write(raw); self.process.stdin.flush()
        except (OSError,BrokenPipeError): raise _fail(FailureClass.MCP_AMBIGUOUS_COMPLETION,"request transmission ambiguous") from None
        stop=self.clock()+timeout_ms/1000
        while True:
            if cancellation is not None and cancellation.is_set(): raise _fail(FailureClass.CANCELLED,"cancelled")
            if self.process.poll() is not None:
                if self.out: raise _fail(FailureClass.TRUNCATED_RESPONSE,"incomplete stdout response")
                raise _fail(FailureClass.MCP_AMBIGUOUS_COMPLETION,"child exited after request")
            remaining=min(stop-self.clock(),deadline.timeout(operation_ms)/1000)
            if remaining<=0: raise _fail(FailureClass.MCP_TIMEOUT,"response deadline")
            for line in self._drain(remaining):
                try: msg=parse_closed_json(line,self.limits,byte_limit=self.limits.mcp_response_bytes)
                except ProviderError as exc: raise _fail(exc.failure.classification,"invalid MCP JSON") from None
                obj=_closed(msg,{"jsonrpc","id","result","error"},{"jsonrpc","id"})
                if obj.get("jsonrpc")!="2.0" or type(obj.get("id")) is not int or obj["id"]!=request_id: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"unsolicited or wrong response ID")
                if ("result" in obj)==("error" in obj): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"bad response shape")
                if "error" in obj:
                    err=_closed(obj["error"],{"code","message","data"},{"code","message"})
                    if type(err["code"]) is not int or not isinstance(err["message"],str): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"bad error")
                    raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"MCP error")
                return CorrelatedMcpResponse(request_id,action,_freeze_json(obj["result"],limits=self.limits),len(line))

    def initialize_and_capture(self, deadline: Deadline, cancellation: Cancellation|None=None) -> ToolSurface:
        init=self._request("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"native-mcp-agent","version":"10.2"}},deadline,self.limits.mcp_initialize_timeout_ms,cancellation=cancellation)
        value=_closed(init.result,{"protocolVersion","capabilities","serverInfo","instructions"},{"protocolVersion","capabilities","serverInfo"})
        if not isinstance(value["protocolVersion"],str) or not isinstance(value["capabilities"],dict) or not isinstance(value["serverInfo"],dict): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"bad initialize")
        assert self.process and self.process.stdin; deadline.timeout(self.limits.mcp_initialize_timeout_ms)
        try: self.process.stdin.write(_canon({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})+b"\n"); self.process.stdin.flush()
        except (OSError,BrokenPipeError): raise _fail(FailureClass.MCP_AMBIGUOUS_COMPLETION,"initialized notification failed") from None
        listed=self._request("tools/list",{},deadline,self.limits.mcp_tools_list_timeout_ms,cancellation=cancellation)
        self.surface=capture_tool_surface(listed.result,self.limits); return self.surface

    def revalidate_surface(self, deadline: Deadline, cancellation: Cancellation|None=None) -> None:
        if self.surface is None: raise _fail(FailureClass.LOCAL_POLICY_FAILURE,"surface absent")
        later=capture_tool_surface(self._request("tools/list",{},deadline,self.limits.mcp_tools_list_timeout_ms,cancellation=cancellation).result,self.limits)
        if later.identity!=self.surface.identity: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"tool surface changed")

    def execute(self, action: AuthorizedMcpAction, deadline: Deadline, cancellation: Cancellation|None=None) -> CorrelatedMcpResponse:
        if not isinstance(action,AuthorizedMcpAction) or self.surface is None or action.surface_identity!=self.surface.identity: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"forged or stale authorization")
        tool=next((x for x in self.surface.tools if x.name==action.name),None)
        if tool is None or not isinstance(action.action_id,LocalActionIdentity): raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"tool unauthorized")
        try:
            frozen=_freeze_json(action.arguments,limits=self.limits); _validate_schema(frozen,tool.parameters,self.limits)
        except ProviderError: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"arguments unauthorized") from None
        if not isinstance(frozen,dict) or _canon(frozen)!=action.argument_bytes or len(action.argument_bytes)>self.limits.tool_argument_bytes: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"arguments changed")
        response=self._request("tools/call",{"name":action.name,"arguments":frozen},deadline,self.limits.mcp_call_timeout_ms,action,cancellation)
        return CorrelatedMcpResponse(response.request_id,action.action_id,_validate_tool_result(response.result,self.limits),response.byte_count)

    def close(self, deadline: Deadline|None=None, *, suppress: bool=False) -> None:
        process=self.process
        if process is None: return
        try:
            if process.stdin: process.stdin.close()
            wait=(deadline.timeout(self.limits.graceful_shutdown_timeout_ms)/1000 if deadline else self.limits.graceful_shutdown_timeout_ms/1000)
            if process.poll() is None: process.terminate(); process.wait(wait)
        except (subprocess.TimeoutExpired,ProviderError):
            try: process.kill(); process.wait(1.0)
            except (OSError,subprocess.TimeoutExpired):
                if not suppress: raise _fail(FailureClass.MCP_PROCESS_EXIT,"kill/reap failed") from None
        except (OSError,BrokenPipeError):
            if not suppress: raise _fail(FailureClass.MCP_PROCESS_EXIT,"shutdown failed") from None
        finally:
            if self.selector: self.selector.close()
            for stream in (process.stdout,process.stderr):
                try:
                    if stream: stream.close()
                except OSError: pass
            self.selector=None; self.process=None

def _validate_tool_result(value: Any, limits: Limits) -> Mapping[str,Any]:
    obj=_closed(value,{"content","isError"},{"content"})
    if not isinstance(obj["content"],(list,tuple)) or len(obj["content"])>limits.object_array_items or ("isError" in obj and type(obj["isError"]) is not bool): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"bad tool result")
    blocks=[]
    for block in obj["content"]:
        item=_closed(block,{"type","text"},{"type","text"})
        if item["type"]!="text" or not isinstance(item["text"],str) or len(item["text"].encode())>limits.message_bytes: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"unsupported content")
        blocks.append({"type":"text","text":redact_json({"message":item["text"]})["message"]})
    output={"content":blocks}
    if "isError" in obj: output["isError"]=obj["isError"]
    return _freeze_json(output,limits=limits)

@dataclass(frozen=True)
class OrchestrationOutcome:
    outcome: str; evidence: tuple[Evidence,...]; execution_order: tuple[LocalActionIdentity,...]; transcript: bytes

class Orchestrator:
    def __init__(self, client:McpStdioClient, provider:ProviderTurn, *, limits:Limits=DEFAULT_LIMITS, context:str="offline", clock:Callable[[],float]=time.monotonic, cancellation:Cancellation|None=None) -> None:
        self.client,self.provider,self.limits,self.context,self.clock,self.cancellation=client,provider,limits,context,clock,cancellation
        self.actions:set[str]=set(); self.call_ids:dict[str,bytes]={}; self.evidence:list[Evidence]=[]; self.order:list[LocalActionIdentity]=[]; self.transcript=Phase10Transcript(limits)
    def _action(self,p:ProviderToolCallProposal,surface:ToolSurface)->LocalActionIdentity: return LocalActionIdentity(hashlib.sha256(_canon({"surface":surface.identity,"name":p.name,"arguments":p.arguments,"context":self.context})).hexdigest()[:32])
    def _outcome(self,outcome:str)->OrchestrationOutcome:
        self.transcript.add("outcome",outcome=outcome); raw=self.transcript.to_json_bytes()
        parse_phase_10_2_transcript(raw,self.limits); return OrchestrationOutcome(outcome,tuple(self.evidence),tuple(self.order),raw)
    def run(self, request:ProviderRequest) -> OrchestrationOutcome:
        deadline=Deadline(self.clock()+self.limits.orchestration_total_timeout_ms/1000,self.clock)
        try:
            self.transcript.add("process_start")
            surface=self.client.initialize_and_capture(deadline,self.cancellation); self.transcript.add("surface",surface=surface.identity)
            for turn in range(self.limits.provider_turn_count):
                if self.cancellation and self.cancellation.is_set(): return self._outcome("cancelled")
                timeout=deadline.timeout(self.limits.provider_total_timeout_ms)
                bounded=ProviderRequest(request.model,request.messages,surface.tools,request.max_output_tokens,request.correlation_id,request.generation)
                raw=bounded.to_json_bytes(self.limits); self.transcript.add("provider_turn",turn=str(turn),bytes=str(len(raw)))
                response=self.provider.turn(bounded,tuple(self.evidence),timeout_ms=timeout,cancellation=self.cancellation)
                if deadline.remaining_ms()<=0: return self._outcome("deadline")
                if isinstance(response,ProviderFinalMessage): return self._outcome("final")
                proposals=tuple(response)
                if len(proposals)>self.limits.proposed_tool_call_count or len(proposals)>self.limits.mcp_calls_per_turn: return self._outcome("rejected")
                prepared=[]
                for p in proposals:
                    if not isinstance(p,ProviderToolCallProposal): return self._outcome("rejected")
                    tool=next((x for x in surface.tools if x.name==p.name),None)
                    if tool is None: return self._outcome("rejected")
                    frozen=_freeze_json(p.arguments,limits=self.limits); _validate_schema(frozen,tool.parameters,self.limits); content=_canon({"name":p.name,"arguments":frozen}); aid=self._action(p,surface)
                    if str(p.call_id) in self.call_ids or aid.value in self.actions or any(x[1].value==aid.value for x in prepared): return self._outcome("duplicate")
                    prepared.append((p,aid,content,frozen))
                for index,(p,aid,content,frozen) in enumerate(prepared):
                    if self.cancellation and self.cancellation.is_set(): self.transcript.add("skipped",proposal=str(p.call_id)); return self._outcome("cancelled")
                    if len(self.order)>=self.limits.mcp_total_calls or deadline.remaining_ms()<=0: self.transcript.add("skipped",proposal=str(p.call_id)); return self._outcome("deadline")
                    auth=AuthorizedMcpAction(surface.identity,aid,str(p.call_id),p.name,frozen,_canon(frozen)); self.call_ids[str(p.call_id)]=content; self.actions.add(aid.value); self.transcript.add("authorized",action=aid.value,proposal=str(p.call_id))
                    try:
                        response=self.client.execute(auth,deadline,self.cancellation); self.order.append(aid); self.evidence.append(Evidence(aid,response.request_id,response.result)); self.transcript.add("mcp_response",action=aid.value,response=str(response.request_id))
                    except ProviderError as exc:
                        self.transcript.add("failed",action=aid.value,failure=exc.failure.classification.value)
                        for later,*_ in prepared[index+1:]: self.transcript.add("skipped",proposal=str(later.call_id))
                        return self._outcome("cancelled" if exc.failure.classification is FailureClass.CANCELLED else "failed")
            return self._outcome("budget")
        except ProviderError as exc:
            self.transcript.add("failed",failure=exc.failure.classification.value); return self._outcome("deadline" if exc.failure.classification is FailureClass.MCP_TIMEOUT else "failed")
        finally:
            self.client.close(deadline,suppress=True)
