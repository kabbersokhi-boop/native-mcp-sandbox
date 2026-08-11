#!/usr/bin/env python3
"""Phase 10.3 deterministic adversarial assurance for Phase 10.1/10.2."""
from __future__ import annotations

from dataclasses import replace
import json, os, socket, subprocess, sys, threading, time, unittest
from pathlib import Path

ROOT=os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0, ROOT)
from agent.native_mcp_agent.contracts import (AdvertisedTool, EvidenceProvenance, MessageRole, ProviderFinalMessage, ProviderMessage, ProviderRequest, ProviderToolCallProposal, RequestCorrelationId, ToolCallId, parse_closed_json, parse_provider_response)
from agent.native_mcp_agent.endpoint_policy import ValidatedEndpoint, redirect_rejection, validate_fake_loopback_endpoint, validate_production_endpoint
from agent.native_mcp_agent.environment import build_child_environment
from agent.native_mcp_agent.errors import FailureClass, ProviderError, failure, http_failure
from agent.native_mcp_agent.limits import DEFAULT_LIMITS
from agent.native_mcp_agent.mcp_orchestrator import (AuthorizedMcpAction, CancellationToken, Deadline, Evidence, McpStdioClient, Orchestrator, ScriptedProvider, capture_tool_surface)
from agent.native_mcp_agent.redaction import redact_exception, redact_headers, redact_json, redact_provider_excerpt, redact_text
from agent.native_mcp_agent.retry import decide_retry
from agent.native_mcp_agent.transcript import Phase10Transcript, TranscriptEvent, parse_phase_10_2_transcript, parse_transcript
from agent.native_mcp_agent.transport import LoopbackFakeTransport

CHILD=os.path.join(ROOT,"tests","fake_mcp_stdio_child.py")
SENTINELS=("API_KEY_10_3_UNIQUE","Authorization: Bearer TOKEN_10_3_UNIQUE","proxy://user:pass@host","SECRET_STORE_10_3_UNIQUE","/absolute/phase10_3/sentinel","pid=424242","--command-secret=CMD_10_3")
TOOLS=(AdvertisedTool("logs.search",{"type":"object","properties":{"query":{"type":"string","maxLength":32}},"required":["query"],"additionalProperties":False}),)
def req(): return ProviderRequest("synthetic",(ProviderMessage(MessageRole.USER,"investigate"),),TOOLS,32,RequestCorrelationId("req-10-3"))
def proposal(i="call-1",q="x"): return ProviderToolCallProposal(ToolCallId(i),"logs.search",{"query":q})
def client(case="normal",limits=DEFAULT_LIMITS): return McpStdioClient(sys.executable,(CHILD,case),child_allowlist=("LANG",),parent_environment={"LANG":"C",**{f"X{i}":v for i,v in enumerate(SENTINELS)}},limits=limits)
def run(case="normal",responses=(),limits=DEFAULT_LIMITS,cancellation=None):
 c=client(case,limits); return c,Orchestrator(c,ScriptedProvider(tuple(responses)),limits=limits,cancellation=cancellation).run(req())
def events(out): return {x["event"] for x in parse_phase_10_2_transcript(out.transcript)}

class ProviderAdversarialTests(unittest.TestCase):
 def test_hostile_provider_forms_fail_before_execution(self):
  bad=(b"{",b'{"message":{"role":"assistant","content":"x"}',b'{"message":{"role":"assistant","content":"x"},"x":1}',b'{"message":{"role":"assistant","content":"x"},"toolCalls":[]}',b'{"toolCalls":[{"id":"","name":"logs.search","arguments":"{}"}]}',b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{"}]}',b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"[]"}]}')
  for raw in bad:
   with self.subTest(raw=raw),self.assertRaises(ProviderError): parse_provider_response(raw,advertised_tools=TOOLS)
 def test_duplicate_unknown_missing_types_nesting_cardinality_and_limits_are_closed(self):
  for raw in (b'{"a":1,"a":2}',b'{"message":1}',b'{"toolCalls":{}}',b'{"message":{"role":"assistant"}}'):
   with self.subTest(raw=raw),self.assertRaises(ProviderError): parse_provider_response(raw,advertised_tools=TOOLS)
  with self.assertRaises(ProviderError): parse_closed_json(b'{"a":{"b":{"c":1}}}',replace(DEFAULT_LIMITS,json_nesting_depth=2))
  with self.assertRaises(ProviderError): parse_closed_json(b'{"a":1,"b":2}',replace(DEFAULT_LIMITS,object_array_items=1))
  raw=b'{"message":{"role":"assistant","content":"x"}}'; self.assertEqual(parse_provider_response(raw,advertised_tools=TOOLS).message.content,"x")
  with self.assertRaises(ProviderError): parse_provider_response(raw+b" ",advertised_tools=TOOLS,limits=replace(DEFAULT_LIMITS,provider_response_bytes=len(raw)))

class EvidenceForgeryTests(unittest.TestCase):
 def test_provider_text_never_becomes_validated_evidence(self):
  c,out=run(responses=(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"I fabricated evidence response=999")),))
  self.assertEqual(out.outcome,"final"); self.assertEqual(out.evidence,()); self.assertIsNone(c.process)
  forged=Evidence(proposal().action_identity,999,{"content":[]},EvidenceProvenance.VALIDATED_MCP_EVIDENCE)
  self.assertEqual(forged.response_id,999); self.assertEqual(run(responses=(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")),))[1].evidence,())
 def test_only_validated_correlated_mcp_result_becomes_evidence(self):
  _,out=run(responses=((proposal(),),ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))))
  self.assertEqual(len(out.evidence),1); self.assertEqual(out.evidence[0].provenance,EvidenceProvenance.VALIDATED_MCP_EVIDENCE); self.assertEqual(out.evidence[0].response_id,3)

class CorrelationAttackTests(unittest.TestCase):
 def test_unexpected_and_malformed_correlations_fail_closed(self):
  for case in ("wrong_id","unsolicited","future_id","duplicate_completed","malformed","truncated"):
   c,out=run(case); self.assertEqual(out.outcome,"failed",case); self.assertEqual(out.evidence,()); self.assertIsNone(c.process)
 def test_failed_action_cannot_cross_action_boundary(self):
  c,out=run("exit",((proposal("call-1","a"),proposal("call-2","b")),)); self.assertEqual(out.execution_order,()); self.assertIn("skipped",events(out)); self.assertIsNone(c.process)

class ReplayAttackTests(unittest.TestCase):
 def test_replay_forms_never_execute_twice(self):
  cases=(((proposal("call-1"),proposal("call-1")),),((proposal("call-1","a"),proposal("call-1","b")),),((proposal("call-1","a"),proposal("call-2","a")),),((proposal("call-1"),),(proposal("call-1"),)))
  for replies in cases:
   _,out=run(responses=replies); self.assertEqual(len(out.execution_order),0 if len(replies)==1 else 1); self.assertEqual(out.outcome,"duplicate")
 def test_ambiguous_completion_does_not_retry_execution(self):
  _,out=run("exit",((proposal(),),)); self.assertEqual(out.execution_order,()); self.assertEqual(out.evidence,())

class MultipleCallStopTests(unittest.TestCase):
 def test_failure_timeout_and_cancellation_skip_later_proposals(self):
  for case,limits in (("malformed_result",DEFAULT_LIMITS),("delay",replace(DEFAULT_LIMITS,mcp_call_timeout_ms=20))):
   _,out=run(case,((proposal("call-1","a"),proposal("call-2","b")),),limits); self.assertEqual(len(out.execution_order),0); self.assertIn("skipped",events(out))
  token=CancellationToken(); t=threading.Thread(target=lambda:(time.sleep(.08),token.cancel())); t.start(); _,out=run("delay",((proposal("call-1","a"),proposal("call-2","b")),),cancellation=token); t.join(); self.assertEqual(out.outcome,"cancelled"); self.assertIn("skipped",events(out))

class FailureTaxonomyTests(unittest.TestCase):
 def test_every_failure_class_has_exact_retry_contract(self):
  retryable={FailureClass.HTTP_408_REQUEST_TIMEOUT,FailureClass.HTTP_429_RATE_LIMITED,FailureClass.DNS_OR_CONNECTION_FAILURE,FailureClass.CONNECT_TIMEOUT,FailureClass.TRANSIENT_5XX}
  for kind in FailureClass:
   decision=decide_retry(failure(kind),completed_attempts=0,remaining_ms=1000,limits=DEFAULT_LIMITS)
   self.assertEqual(decision.eligible,kind in retryable,kind)
  self.assertFalse(decide_retry(failure(FailureClass.HTTP_429_RATE_LIMITED),completed_attempts=DEFAULT_LIMITS.provider_attempt_count,remaining_ms=1000,limits=DEFAULT_LIMITS).eligible)
  self.assertFalse(decide_retry(failure(FailureClass.HTTP_429_RATE_LIMITED,retry_after_ms=1000),completed_attempts=0,remaining_ms=999,limits=DEFAULT_LIMITS).eligible)
  self.assertFalse(decide_retry(http_failure(400),completed_attempts=0,remaining_ms=1000,limits=DEFAULT_LIMITS).eligible)

class SecretSentinelTests(unittest.TestCase):
 def test_unique_sentinels_are_absent_from_every_project_output_boundary(self):
  parent={"LANG":"C",**{f"SECRET_{i}":v for i,v in enumerate(SENTINELS)}}; env=build_child_environment(parent,("LANG",))
  surfaces=[str(env),redact_text(" ".join(SENTINELS),SENTINELS),str(redact_headers({"Authorization":SENTINELS[1],"x":SENTINELS[0]},SENTINELS)),str(redact_json({"diagnostic":" ".join(SENTINELS)},SENTINELS)),redact_exception(Exception(" ".join(SENTINELS)),SENTINELS),redact_provider_excerpt(" ".join(SENTINELS),SENTINELS)]
  c,out=run("secret_result",((proposal(),),)); surfaces.extend((str(c.environment),str(out.evidence),out.transcript.decode()))
  for sentinel in SENTINELS:
   self.assertTrue(all(sentinel not in surface for surface in surfaces),sentinel)

class EndpointPolicyAdversarialTests(unittest.TestCase):
 def test_insecure_userinfo_fragment_tls_redirect_and_destination_attacks_fail(self):
  for url in ("http://example/x","https://u:p@example/x","https://example/x#f","https:///x","ftp://example/x"):
   with self.subTest(url=url),self.assertRaises(ProviderError): validate_production_endpoint(url)
  with self.assertRaises(ProviderError): validate_production_endpoint("https://example/x",verify_tls=False)
  self.assertEqual(redirect_rejection("https://evil").classification,FailureClass.REDIRECT_REJECTED)
  def private(*_): return [(socket.AF_INET,socket.SOCK_STREAM,6,"",("10.0.0.1",1))]
  with self.assertRaises(ProviderError): validate_fake_loopback_endpoint("http://localhost:1/x",allow_loopback_http=True,resolver=private)
 def test_transport_forged_authority_never_connects(self):
  calls=[]; t=LoopbackFakeTransport(connection_factory=lambda *x:calls.append(x))
  with self.assertRaises(ProviderError): t.send(ValidatedEndpoint("http://127.0.0.1:1/x","http","127.0.0.1","10.0.0.1",1,"/x",True),req(),correlation_id="req-10-3")
  self.assertEqual(calls,[])

class TranscriptTamperTests(unittest.TestCase):
 def test_closed_transcript_and_phase10_limit_tampering_fail(self):
  raw=TranscriptEvent("event","adapter","model",RequestCorrelationId("req-10-3"),EvidenceProvenance.LOCAL_CONTROL_EVENT,metadata={"mode":"safe"}).to_json_bytes()
  for mutate in (b'{"schemaVersion":1}',raw[:-1]+b',"x":1}',raw.replace(b'"schemaVersion":1',b'"schemaVersion":2')):
   with self.subTest(mutate=mutate),self.assertRaises(ProviderError): parse_transcript(mutate)
  limited=Phase10Transcript(replace(DEFAULT_LIMITS,transcript_bytes=150)); limited.add("process_start"); limited.add("initialize_request"); data=limited.to_json_bytes(); parsed=parse_phase_10_2_transcript(data); self.assertEqual(sum(x["event"]=="transcript_limit" for x in parsed),1)
 def test_repeated_project_outputs_are_byte_identical(self):
  a=run(responses=(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")),))[1].transcript; b=run(responses=(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")),))[1].transcript; self.assertEqual(a,b)

class BudgetDeadlineLifecycleTests(unittest.TestCase):
 def test_budget_exact_one_over_and_lifecycle_edges_fail_closed(self):
  raw=b'{"x":1}'; self.assertEqual(parse_closed_json(raw,replace(DEFAULT_LIMITS,provider_response_bytes=len(raw))),{"x":1})
  with self.assertRaises(ProviderError): parse_closed_json(raw,replace(DEFAULT_LIMITS,provider_response_bytes=len(raw)-1))
  for case in ("oversized","flood","truncated","exit"):
   c,out=run(case); self.assertEqual(out.outcome,"failed"); self.assertIsNone(c.process)
 def test_expiry_cancellation_and_shutdown_have_no_later_authority(self):
  limits=replace(DEFAULT_LIMITS,orchestration_total_timeout_ms=30,mcp_call_timeout_ms=500); c,out=run("delay",((proposal("call-1"),proposal("call-2")),),limits); self.assertEqual(out.evidence,()); self.assertIsNone(c.process)
  c=client("ignore_shutdown",replace(DEFAULT_LIMITS,graceful_shutdown_timeout_ms=10)); d=Deadline(c.clock()+1,c.clock); c.initialize_and_capture(d); self.assertEqual(c.close(d,suppress=True),"kill")

class ToolSurfaceAuthorizationSerialScopeTests(unittest.TestCase):
 def test_tool_surface_and_forged_authorization_are_rejected_before_write(self):
  bad=({"tools":[{"name":"x","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":False}},{"name":"x","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":False}}]}, {"tools":[{"name":"x","inputSchema":{}}]})
  for value in bad:
   with self.subTest(value=value),self.assertRaises(ProviderError): capture_tool_surface(value)
  c=client(); d=Deadline(c.clock()+1,c.clock); surface=c.initialize_and_capture(d); before=c.next_id; forged=AuthorizedMcpAction(surface.identity,proposal().action_identity,"call-1","logs.search",{"query":"x"},b'{"query":"changed"}')
  with self.assertRaises(ProviderError): c.execute(forged,d)
  self.assertEqual(c.next_id,before); c.close(d,suppress=True)
 def test_serial_fixture_and_scope_guard(self):
  _,out=run("serial_probe",((proposal("call-1","a"),proposal("call-2","b")),ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))); self.assertEqual(len(out.execution_order),2); self.assertIn("maxActive=1",str(out.evidence))
  forbidden=("socket(","curl ","system(","OpenAI", "NVIDIA_API_KEY")
  native="\n".join(Path(ROOT,"src",name).read_text(encoding="utf-8") for name in os.listdir(os.path.join(ROOT,"src")) if name.endswith((".cpp",".hpp")))
  self.assertTrue(all(token not in native for token in forbidden))

if __name__=="__main__": unittest.main(verbosity=2)
