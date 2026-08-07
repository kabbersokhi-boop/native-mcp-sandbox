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
def provider(*responses,delay_ms=0): return ScriptedProvider(tuple(responses),delay_ms=delay_ms)
class Tests(unittest.TestCase):
 def test_lifecycle_environment_and_cleanup(self):
  c=client(); out=Orchestrator(c,provider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req())
  events=parse_phase_10_2_transcript(out.transcript)
  self.assertEqual(out.outcome,"final"); self.assertIsNone(c.process); self.assertEqual(c.environment,{"LANG":"C"}); self.assertTrue(events)
  self.assertTrue({"process_start","initialize_request","initialize_response","initialized_notification","tools_list_request","tools_list_response","surface_captured","provider_turn_start","provider_turn_response","shutdown_start","shutdown_complete","outcome"}.issubset({event["event"] for event in events}))
 def test_bad_json_and_response_ids_fail_closed(self):
  for case in ("malformed","duplicate_keys","wrong_id","unsolicited","future_id","truncated","oversized","flood"):
   c=client(case); out=Orchestrator(c,provider()).run(req()); self.assertEqual(out.outcome,"failed"); self.assertIsNone(c.process)
 def test_duplicate_completed_response_is_rejected(self):
  c=client("duplicate_completed"); out=Orchestrator(c,provider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req())
  self.assertEqual(out.outcome,"failed"); self.assertIsNone(c.process)
 def test_ignored_shutdown_is_killed_and_reaped(self):
  c=client("ignore_shutdown",replace(DEFAULT_LIMITS,graceful_shutdown_timeout_ms=20)); out=Orchestrator(c,provider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))),limits=c.limits).run(req())
  self.assertEqual(out.outcome,"final"); self.assertIsNone(c.process)
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
  c=client("secret_result"); out=Orchestrator(c,provider((proposal("call-1","a"),proposal("call-2","b")),ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req())
  self.assertEqual(len(out.evidence),2); self.assertNotIn("SECRET_SENTINEL",str(out.evidence)); self.assertEqual(len(out.execution_order),2)
 def test_failure_skips_later_and_reaps(self):
  c=client("exit"); out=Orchestrator(c,provider((proposal("call-1","a"),proposal("call-2","b")))).run(req())
  self.assertEqual(out.outcome,"failed"); self.assertEqual(len(out.execution_order),0); self.assertIn(b"skipped",out.transcript); self.assertIsNone(c.process)
 def test_deadline_no_evidence_after_expiry(self):
  limits=replace(DEFAULT_LIMITS,orchestration_total_timeout_ms=100,mcp_call_timeout_ms=500); c=client("delay",limits); started=time.monotonic()
  out=Orchestrator(c,provider((proposal("call-1"),)),limits=limits).run(req())
  self.assertIn(out.outcome,{"failed","deadline"}); self.assertLess(time.monotonic()-started,.16); self.assertEqual(len(out.evidence),0); self.assertIsNone(c.process)
 def test_provider_late_response_discarded(self):
  limits=replace(DEFAULT_LIMITS,orchestration_total_timeout_ms=50); c=client(limits=limits); out=Orchestrator(c,provider((proposal("call-1"),),delay_ms=80),limits=limits).run(req())
  self.assertIn(out.outcome,{"deadline","failed"}); self.assertEqual(len(out.evidence),0)
 def test_scripted_provider_timeout_does_not_sleep_full_delay(self):
  provider=ScriptedProvider((ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")),),delay_ms=200)
  started=time.monotonic()
  with self.assertRaises(ProviderError): provider.turn(req(),(),timeout_ms=50,cancellation=None)
  self.assertLess(time.monotonic()-started,.12)
 def test_unbounded_provider_callback_is_not_supported(self):
  class Unbounded:
   def turn(self,*_args,**_kwargs): return ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))
  with self.assertRaises(ProviderError): Orchestrator(client(),Unbounded())
 def test_result_contract_and_transcript_determinism(self):
  c=client("malformed_result"); out=Orchestrator(c,provider((proposal("call-1"),))).run(req()); self.assertEqual(out.outcome,"failed")
  a=Orchestrator(client(),provider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req()).transcript
  b=Orchestrator(client(),provider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req()).transcript
  self.assertEqual(a,b)
if __name__=="__main__": unittest.main(verbosity=2)
