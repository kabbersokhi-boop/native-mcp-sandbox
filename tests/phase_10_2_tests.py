#!/usr/bin/env python3
from __future__ import annotations
import os, sys, time, unittest
from dataclasses import replace
ROOT=os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0,os.path.join(ROOT,"agent"))
from native_mcp_agent.contracts import ProviderMessage,ProviderRequest,ProviderToolCallProposal,ProviderFinalMessage,RequestCorrelationId,ToolCallId,MessageRole
from native_mcp_agent.errors import ProviderError
from native_mcp_agent.limits import DEFAULT_LIMITS
from native_mcp_agent.mcp_orchestrator import McpStdioClient,Orchestrator,Deadline,AuthorizedMcpAction,ScriptedProvider
from native_mcp_agent.transcript import parse_phase_10_2_transcript
CHILD=os.path.join(ROOT,"tests","fake_mcp_stdio_child.py")
def req(): return ProviderRequest("fake",(ProviderMessage(MessageRole.USER,"investigate"),),(),32,RequestCorrelationId("req-10-2"))
def proposal(i,q="x"): return ProviderToolCallProposal(ToolCallId(i),"logs.search",{"query":q})
def client(case="normal",limits=DEFAULT_LIMITS): return McpStdioClient(sys.executable,(CHILD,case),child_allowlist=("LANG",),parent_environment={"LANG":"C","SECRET_SENTINEL":"x","HTTP_PROXY":"bad"},limits=limits)
def deadline(c,ms=1000): return Deadline(c.clock()+ms/1000,c.clock)
class FakeProvider:
 def __init__(self,*responses,delay=0): self.responses=iter(responses); self.delay=delay; self.timeouts=[]
 def turn(self,request,evidence,*,timeout_ms,cancellation):
  self.timeouts.append(timeout_ms)
  if self.delay: time.sleep(self.delay)
  return next(self.responses)
class Tests(unittest.TestCase):
 def test_lifecycle_environment_and_cleanup(self):
  c=client(); out=Orchestrator(c,FakeProvider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req())
  self.assertEqual(out.outcome,"final"); self.assertIsNone(c.process); self.assertEqual(c.environment,{"LANG":"C"}); self.assertTrue(parse_phase_10_2_transcript(out.transcript))
 def test_bad_json_and_response_ids_fail_closed(self):
  for case in ("malformed","duplicate_keys","wrong_id","unsolicited","future_id","flood"):
   c=client(case); out=Orchestrator(c,FakeProvider(())).run(req()); self.assertEqual(out.outcome,"failed"); self.assertIsNone(c.process)
 def test_changed_surface_and_final_boundary(self):
  c=client("changing_tools"); d=deadline(c); c.initialize_and_capture(d)
  with self.assertRaises(ProviderError): c.revalidate_surface(d)
  c.close(d,suppress=True)
 def test_direct_forged_authorization_never_writes(self):
  c=client(); d=deadline(c); s=c.initialize_and_capture(d); before=c.next_id
  bad=AuthorizedMcpAction(s.identity,proposal("call-1").action_identity,"call-1","nope",{},b"{}")
  with self.assertRaises(ProviderError): c.execute(bad,d)
  self.assertEqual(c.next_id,before); c.close(d,suppress=True)
 def test_serial_evidence_and_redaction(self):
  c=client("secret_result"); out=Orchestrator(c,FakeProvider((proposal("call-1","a"),proposal("call-2","b")),ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req())
  self.assertEqual(len(out.evidence),2); self.assertNotIn("SECRET_SENTINEL",str(out.evidence)); self.assertEqual(len(out.execution_order),2)
 def test_failure_skips_later_and_reaps(self):
  c=client("exit"); out=Orchestrator(c,FakeProvider((proposal("call-1","a"),proposal("call-2","b")))).run(req())
  self.assertEqual(out.outcome,"failed"); self.assertEqual(len(out.execution_order),0); self.assertIn(b"skipped",out.transcript); self.assertIsNone(c.process)
 def test_deadline_no_evidence_after_expiry(self):
  limits=replace(DEFAULT_LIMITS,orchestration_total_timeout_ms=100,mcp_call_timeout_ms=500); c=client("delay",limits); started=time.monotonic()
  out=Orchestrator(c,FakeProvider((proposal("call-1"),)),limits=limits).run(req())
  self.assertEqual(out.outcome,"failed"); self.assertLess(time.monotonic()-started,.16); self.assertEqual(len(out.evidence),0); self.assertIsNone(c.process)
 def test_provider_late_response_discarded(self):
  limits=replace(DEFAULT_LIMITS,orchestration_total_timeout_ms=50); c=client(limits=limits); out=Orchestrator(c,FakeProvider((proposal("call-1"),),delay=.08),limits=limits).run(req())
  self.assertEqual(out.outcome,"deadline"); self.assertEqual(len(out.evidence),0)
 def test_scripted_provider_timeout_does_not_sleep_full_delay(self):
  provider=ScriptedProvider((ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")),),delay_ms=200)
  started=time.monotonic()
  with self.assertRaises(ProviderError): provider.turn(req(),(),timeout_ms=50,cancellation=None)
  self.assertLess(time.monotonic()-started,.12)
 def test_result_contract_and_transcript_determinism(self):
  c=client("malformed_result"); out=Orchestrator(c,FakeProvider((proposal("call-1"),))).run(req()); self.assertEqual(out.outcome,"failed")
  a=Orchestrator(client(),FakeProvider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req()).transcript
  b=Orchestrator(client(),FakeProvider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req()).transcript
  self.assertEqual(a,b)
if __name__=="__main__": unittest.main(verbosity=2)
