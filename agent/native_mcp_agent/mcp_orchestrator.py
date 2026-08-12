"""Closed, serial and deadline-bounded offline MCP orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib, json, os, selectors, subprocess, threading, time
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
    def turn(self, request: ProviderRequest, evidence: tuple[Evidence, ...], *, timeout_ms: int, cancellation: Cancellation | None) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]: ...

@dataclass
class ScriptedProvider:
    """The only Phase 10.2 provider double; it never outlives its budget."""
    responses: tuple[ProviderFinalMessage | Sequence[ProviderToolCallProposal], ...]
    delay_ms: int = 0
    _index: int = 0
    def turn(self, request: ProviderRequest, evidence: tuple[Evidence, ...], *, timeout_ms: int, cancellation: Cancellation | None) -> ProviderFinalMessage | Sequence[ProviderToolCallProposal]:
        if not isinstance(timeout_ms, int) or timeout_ms <= 0: raise _fail(FailureClass.TOTAL_REQUEST_TIMEOUT,"provider deadline")
        end=time.monotonic()+timeout_ms/1000
        while time.monotonic() < end and self.delay_ms > 0:
            if cancellation is not None and cancellation.is_set(): raise _fail(FailureClass.CANCELLED,"provider cancelled")
            time.sleep(min(.005, max(0,end-time.monotonic())))
            self.delay_ms -= 5
        if cancellation is not None and cancellation.is_set(): raise _fail(FailureClass.CANCELLED,"provider cancelled")
        if self.delay_ms > 0 or time.monotonic() >= end: raise _fail(FailureClass.TOTAL_REQUEST_TIMEOUT,"provider timed out")
        if self._index >= len(self.responses): raise _fail(FailureClass.PERMANENT_PROVIDER_FAILURE,"script exhausted")
        result=self.responses[self._index]; self._index += 1
        return result

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
        self._issuer = object()
        self._authorizations: dict[int, tuple[str, LocalActionIdentity, str, str, Mapping[str, Any], bytes]] = {}
        self._startup_pending=True; self.last_initialize: CorrelatedMcpResponse|None=None; self.last_tools_list: CorrelatedMcpResponse|None=None

    def authorize(self, action_id: LocalActionIdentity, proposal_id: str, name: str, arguments: Mapping[str, Any]) -> AuthorizedMcpAction:
        if self.surface is None: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"surface absent")
        frozen = _freeze_json(arguments, limits=self.limits)
        if not isinstance(frozen, dict): raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"arguments invalid")
        tool=next((x for x in self.surface.tools if x.name==name),None)
        if tool is None: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"tool unauthorized")
        _validate_schema(frozen,tool.parameters,self.limits)
        value=AuthorizedMcpAction(self.surface.identity,action_id,proposal_id,name,frozen,_canon(frozen))
        object.__setattr__(value,"_issuer",self._issuer)
        self._authorizations[id(value)] = (value.surface_identity, value.action_id, value.proposal_id, value.name, value.arguments, value.argument_bytes)
        return value

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
            # stderr is never a protocol surface.  Retain only a fixed marker
            # for diagnostics so hostile child output cannot become a
            # project-owned secret-bearing buffer.
            target.extend(data if key.data=="out" else b"<redacted>")
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
        # Popen is a trusted local primitive and cannot be safely preempted by
        # the standard library.  Its earliest enforceable readiness boundary is
        # the first initialize response, which is therefore also startup-bound.
        configured=min(operation_ms, self.limits.process_startup_timeout_ms) if self._startup_pending else operation_ms
        timeout_ms=deadline.timeout(configured); request_id=self.next_id; self.next_id+=1
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
            # Poll cancellation at a bounded cadence instead of sleeping through
            # a full request timeout.
            remaining=min(stop-self.clock(),deadline.timeout(operation_ms)/1000,0.01)
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
                response=CorrelatedMcpResponse(request_id,action,_freeze_json(obj["result"],limits=self.limits),len(line))
                if method == "initialize": self._startup_pending=False
                return response

    def initialize_and_capture(self, deadline: Deadline, cancellation: Cancellation|None=None) -> ToolSurface:
        init=self._request("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"native-mcp-agent","version":"10.2"}},deadline,self.limits.mcp_initialize_timeout_ms,cancellation=cancellation)
        self.last_initialize=init
        value=_closed(init.result,{"protocolVersion","capabilities","serverInfo","instructions"},{"protocolVersion","capabilities","serverInfo"})
        if not isinstance(value["protocolVersion"],str) or not isinstance(value["capabilities"],dict) or not isinstance(value["serverInfo"],dict): raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"bad initialize")
        assert self.process and self.process.stdin; deadline.timeout(self.limits.mcp_initialize_timeout_ms)
        try: self.process.stdin.write(_canon({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})+b"\n"); self.process.stdin.flush()
        except (OSError,BrokenPipeError): raise _fail(FailureClass.MCP_AMBIGUOUS_COMPLETION,"initialized notification failed") from None
        listed=self._request("tools/list",{},deadline,self.limits.mcp_tools_list_timeout_ms,cancellation=cancellation)
        self.last_tools_list=listed
        self.surface=capture_tool_surface(listed.result,self.limits); return self.surface

    def revalidate_surface(self, deadline: Deadline, cancellation: Cancellation|None=None) -> None:
        if self.surface is None: raise _fail(FailureClass.LOCAL_POLICY_FAILURE,"surface absent")
        later=capture_tool_surface(self._request("tools/list",{},deadline,self.limits.mcp_tools_list_timeout_ms,cancellation=cancellation).result,self.limits)
        if later.identity!=self.surface.identity: raise _fail(FailureClass.MCP_PROTOCOL_FAILURE,"tool surface changed")

    def execute(self, action: AuthorizedMcpAction, deadline: Deadline, cancellation: Cancellation|None=None) -> CorrelatedMcpResponse:
        expected=self._authorizations.get(id(action))
        actual=(action.surface_identity, action.action_id, action.proposal_id, action.name, action.arguments, action.argument_bytes) if isinstance(action,AuthorizedMcpAction) else None
        if not isinstance(action,AuthorizedMcpAction) or action._issuer is not self._issuer or self.surface is None or action.surface_identity!=self.surface.identity or expected != actual: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"forged or stale authorization")
        tool=next((x for x in self.surface.tools if x.name==action.name),None)
        if tool is None or not isinstance(action.action_id,LocalActionIdentity): raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"tool unauthorized")
        try:
            frozen=_freeze_json(action.arguments,limits=self.limits); _validate_schema(frozen,tool.parameters,self.limits)
        except ProviderError: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"arguments unauthorized") from None
        if not isinstance(frozen,dict) or _canon(frozen)!=action.argument_bytes or len(action.argument_bytes)>self.limits.tool_argument_bytes: raise _fail(FailureClass.LOCAL_AUTHORIZATION_FAILURE,"arguments changed")
        response=self._request("tools/call",{"name":action.name,"arguments":frozen},deadline,self.limits.mcp_call_timeout_ms,action,cancellation)
        return CorrelatedMcpResponse(response.request_id,action.action_id,_validate_tool_result(response.result,self.limits),response.byte_count)

    def close(self, deadline: Deadline|None=None, *, suppress: bool=False) -> str:
        process=self.process
        if process is None: return "none"
        mode="none"
        try:
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                mode="terminate"
                process.terminate()
                # Every blocking wait under orchestration ownership consumes
                # only a positive slice of its absolute deadline.  Once it is
                # exhausted, signals and poll() are safe but wait() is not.
                graceful_wait=(min(self.limits.graceful_shutdown_timeout_ms, deadline.remaining_ms())/1000
                               if deadline and deadline.remaining_ms()>0 else
                               self.limits.graceful_shutdown_timeout_ms/1000 if deadline is None else None)
                if graceful_wait is not None:
                    try: process.wait(graceful_wait)
                    except subprocess.TimeoutExpired: pass
            if process.poll() is None:
                mode="kill"
                process.kill()
                reap_wait=(deadline.remaining_ms()/1000 if deadline and deadline.remaining_ms()>0 else .2 if deadline is None else None)
                if reap_wait is not None:
                    try: process.wait(reap_wait)
                    except subprocess.TimeoutExpired: pass
                else:
                    # timeout=0 is a non-blocking reap attempt, not a new
                    # lease after the orchestration deadline.
                    try: process.wait(0)
                    except subprocess.TimeoutExpired: pass
            if process.poll() is None:
                mode="unreaped"
                if not suppress: raise _fail(FailureClass.MCP_PROCESS_EXIT,"child unreaped at shutdown deadline")
        except (OSError,BrokenPipeError):
            mode="unreaped"
            if not suppress: raise _fail(FailureClass.MCP_PROCESS_EXIT,"shutdown failed") from None
        finally:
            if self.selector: self.selector.close()
            for stream in (process.stdout,process.stderr):
                try:
                    if stream: stream.close()
                except OSError: pass
            self.selector=None; self.process=None
        return mode

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
        # Phase 10.2 deliberately supports only the project-owned deterministic
        # double.  A future live adapter needs a separate authority decision.
        if not isinstance(provider, ScriptedProvider):
            raise _fail(FailureClass.LOCAL_POLICY_FAILURE, "unbounded provider implementation rejected")
        self.client,self.provider,self.limits,self.context,self.clock,self.cancellation=client,provider,limits,context,clock,cancellation
        self.actions:set[str]=set(); self.call_ids:dict[str,bytes]={}; self.evidence:list[Evidence]=[]; self.order:list[LocalActionIdentity]=[]; self.transcript=Phase10Transcript(limits)
        self._deadline: Deadline|None=None
    def _action(self,p:ProviderToolCallProposal,surface:ToolSurface)->LocalActionIdentity: return LocalActionIdentity(hashlib.sha256(_canon({"surface":surface.identity,"name":p.name,"arguments":p.arguments,"context":self.context})).hexdigest()[:32])
    def _outcome(self,outcome:str)->OrchestrationOutcome:
        # Serialize shutdown control evidence before the immutable transcript.
        self.transcript.add("shutdown_start")
        mode=self.client.close(self._deadline, suppress=True)
        if mode == "terminate": self.transcript.add("shutdown_terminate")
        elif mode == "kill": self.transcript.add("shutdown_terminate"); self.transcript.add("shutdown_kill")
        elif mode == "unreaped": self.transcript.add("shutdown_terminate"); self.transcript.add("shutdown_kill"); self.transcript.add("shutdown_unreaped")
        if mode != "unreaped": self.transcript.add("shutdown_complete")
        self.transcript.add("outcome",outcome=outcome); raw=self.transcript.to_json_bytes()
        parse_phase_10_2_transcript(raw,self.limits); return OrchestrationOutcome(outcome,tuple(self.evidence),tuple(self.order),raw)
    def run(self, request:ProviderRequest) -> OrchestrationOutcome:
        deadline=Deadline(self.clock()+self.limits.orchestration_total_timeout_ms/1000,self.clock)
        self._deadline=deadline
        try:
            self.transcript.add("process_start")
            self.transcript.add("initialize_request")
            surface=self.client.initialize_and_capture(deadline,self.cancellation)
            self.transcript.add("initialize_response",response=str(self.client.last_initialize.request_id if self.client.last_initialize else 1))
            self.transcript.add("initialized_notification")
            self.transcript.add("tools_list_request")
            self.transcript.add("tools_list_response",response=str(self.client.last_tools_list.request_id if self.client.last_tools_list else 2))
            self.transcript.add("surface_captured",surface=surface.identity)
            for turn in range(self.limits.provider_turn_count):
                if self.cancellation and self.cancellation.is_set(): return self._outcome("cancelled")
                timeout=deadline.timeout(self.limits.provider_total_timeout_ms)
                bounded=ProviderRequest(request.model,request.messages,surface.tools,request.max_output_tokens,request.correlation_id,request.generation)
                raw=bounded.to_json_bytes(self.limits); self.transcript.add("provider_turn_start",turn=str(turn),bytes=str(len(raw)))
                response=self.provider.turn(bounded,tuple(self.evidence),timeout_ms=timeout,cancellation=self.cancellation)
                if deadline.remaining_ms()<=0: return self._outcome("deadline")
                try:
                    encoded_response = _canon(_provider_response_value(response))
                except (TypeError, ValueError, ProviderError):
                    return self._outcome("failed")
                if len(encoded_response) > self.limits.provider_response_bytes:
                    return self._outcome("failed")
                self.transcript.add("provider_turn_response",turn=str(turn),bytes=str(len(encoded_response)))
                if isinstance(response,ProviderFinalMessage): return self._outcome("final")
                proposals=tuple(response)
                if len(proposals)>self.limits.proposed_tool_call_count or len(proposals)>self.limits.mcp_calls_per_turn: return self._outcome("rejected")
                prepared=[]
                for proposal_index,p in enumerate(proposals):
                    if not isinstance(p,ProviderToolCallProposal): self.transcript.add("proposal_rejected",proposal="invalid"); return self._outcome("rejected")
                    tool=next((x for x in surface.tools if x.name==p.name),None)
                    if tool is None: self.transcript.add("proposal_rejected",proposal=str(p.call_id)); return self._outcome("rejected")
                    try:
                        frozen=_freeze_json(p.arguments,limits=self.limits); _validate_schema(frozen,tool.parameters,self.limits)
                    except ProviderError:
                        # Proposal validation is a serial authority boundary: a
                        # locally rejected first proposal ends this provider
                        # turn before any later proposal can be authorized or
                        # consume a JSON-RPC tools/call request ID.
                        self.transcript.add("proposal_rejected",proposal=str(p.call_id))
                        for later in proposals[proposal_index + 1:]:
                            if isinstance(later, ProviderToolCallProposal):
                                self.transcript.add("skipped",proposal=str(later.call_id))
                        return self._outcome("rejected")
                    content=_canon({"name":p.name,"arguments":frozen}); aid=self._action(p,surface)
                    if (str(p.call_id) in self.call_ids or aid.value in self.actions
                            or any(str(x[0].call_id) == str(p.call_id) or x[1].value == aid.value for x in prepared)):
                        self.transcript.add("proposal_duplicate",proposal=str(p.call_id)); return self._outcome("duplicate")
                    prepared.append((p,aid,content,frozen))
                for index,(p,aid,content,frozen) in enumerate(prepared):
                    if self.cancellation and self.cancellation.is_set(): self.transcript.add("cancelled"); self.transcript.add("skipped",proposal=str(p.call_id)); return self._outcome("cancelled")
                    if len(self.order)>=self.limits.mcp_total_calls or deadline.remaining_ms()<=0: self.transcript.add("deadline"); self.transcript.add("skipped",proposal=str(p.call_id)); return self._outcome("deadline")
                    auth=self.client.authorize(aid,str(p.call_id),p.name,frozen); self.call_ids[str(p.call_id)]=content; self.actions.add(aid.value); self.transcript.add("authorized",action=aid.value,proposal=str(p.call_id))
                    try:
                        self.transcript.add("mcp_request",action=aid.value,response=str(self.client.next_id))
                        response=self.client.execute(auth,deadline,self.cancellation); self.order.append(aid); self.evidence.append(Evidence(aid,response.request_id,response.result)); self.transcript.add("mcp_response",action=aid.value,response=str(response.request_id)); self.transcript.add("evidence_validated",action=aid.value,response=str(response.request_id))
                    except ProviderError as exc:
                        self.transcript.add("failure",failure=exc.failure.classification.value)
                        for later,*_ in prepared[index+1:]: self.transcript.add("skipped",proposal=str(later.call_id))
                        return self._outcome("cancelled" if exc.failure.classification is FailureClass.CANCELLED else "failed")
            return self._outcome("budget")
        except ProviderError as exc:
            if exc.failure.classification is FailureClass.CANCELLED:
                self.transcript.add("cancelled"); return self._outcome("cancelled")
            timed_out=exc.failure.classification in {FailureClass.MCP_TIMEOUT, FailureClass.TOTAL_REQUEST_TIMEOUT}
            self.transcript.add("deadline" if timed_out else "failure", **({} if timed_out else {"failure":exc.failure.classification.value})); return self._outcome("deadline" if timed_out else "failed")
        finally:
            self.client.close(deadline,suppress=True)

def _provider_response_value(response: ProviderFinalMessage | Sequence[ProviderToolCallProposal]) -> Mapping[str, Any]:
    """Canonical bounded Phase 10.2 provider response representation."""
    if isinstance(response, ProviderFinalMessage):
        return {"kind":"final","role":response.message.role.value,"content":response.message.content}
    calls=[]
    for proposal in response:
        if not isinstance(proposal, ProviderToolCallProposal): raise _fail(FailureClass.INVALID_TOOL_PROPOSAL,"provider response invalid")
        calls.append({"id":str(proposal.call_id),"name":proposal.name,"arguments":proposal.arguments})
    return {"kind":"proposals","calls":calls}
