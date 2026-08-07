#!/usr/bin/env python3
from __future__ import annotations
import os, sys, time, unittest
from dataclasses import replace
ROOT=os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0,os.path.join(ROOT,"agent"))
from native_mcp_agent.contracts import ProviderMessage,ProviderRequest,ProviderToolCallProposal,ProviderFinalMessage,RequestCorrelationId,ToolCallId,MessageRole
from native_mcp_agent.errors import ProviderError
from native_mcp_agent.limits import DEFAULT_LIMITS
from native_mcp_agent.mcp_orchestrator import CancellationToken,McpStdioClient,Orchestrator,Deadline,AuthorizedMcpAction,ScriptedProvider
from native_mcp_agent.transcript import Phase10Transcript,parse_phase_10_2_transcript
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

class DeadlineTests(unittest.TestCase):
 def test_startup_readiness_limit_and_overall_limit(self):
  limits=replace(DEFAULT_LIMITS,process_startup_timeout_ms=40,mcp_initialize_timeout_ms=500,orchestration_total_timeout_ms=500)
  c=client("delayed_start",limits); started=time.monotonic(); out=Orchestrator(c,provider(),limits=limits).run(req())
  self.assertEqual(out.outcome,"deadline"); self.assertLess(time.monotonic()-started,.15); self.assertIsNone(c.process)
  limits=replace(DEFAULT_LIMITS,process_startup_timeout_ms=500,mcp_initialize_timeout_ms=500,orchestration_total_timeout_ms=40)
  c=client("delayed_start",limits); out=Orchestrator(c,provider(),limits=limits).run(req()); self.assertEqual(out.outcome,"deadline"); self.assertIsNone(c.process)
 def test_initialize_and_tools_list_limits(self):
  for case,field in (("delayed_initialize","mcp_initialize_timeout_ms"),("delayed_list","mcp_tools_list_timeout_ms")):
   limits=replace(DEFAULT_LIMITS,**{field:40}); c=client(case,limits); out=Orchestrator(c,provider(),limits=limits).run(req())
   self.assertEqual(out.outcome,"deadline"); self.assertIsNone(c.process)
 def test_provider_response_exact_and_one_over_bytes(self):
  response=ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))
  encoded=len(b'{"content":"done","kind":"final","role":"assistant"}')
  for bound,expected in ((encoded,"final"),(encoded-1,"failed")):
   limits=replace(DEFAULT_LIMITS,provider_response_bytes=bound); c=client(limits=limits)
   self.assertEqual(Orchestrator(c,provider(response),limits=limits).run(req()).outcome,expected)

class AuthorizationBoundaryTests(unittest.TestCase):
 def test_every_invalid_final_action_does_not_write(self):
  limits=replace(DEFAULT_LIMITS,tool_argument_bytes=16)
  c=client(limits=limits); d=deadline(c); surface=c.initialize_and_capture(d); before=c.next_id
  aid=proposal("call-1").action_identity
  deep="x"
  for _ in range(14): deep=[deep]
  invalid=(
   ("unadvertised","nope",{}), ("unknown_field","logs.search",{"other":"x"}),
   ("wrong_type","logs.search",{"query":1}), ("oversized","logs.search",{"query":"x"*20}),
   ("nesting","logs.search",{"query":deep}), ("collection","logs.search",{"query":["x"]*33}),
  )
  for _name,name,args in invalid:
   with self.assertRaises(ProviderError): c.authorize(aid,"call-1",name,args)
   self.assertEqual(c.next_id,before)
  good=c.authorize(aid,"call-1","logs.search",{"query":"x"})
  for action in (replace(good,surface_identity="0"*64),replace(good,argument_bytes=b"{}"),replace(good,action_id=proposal("call-2").action_identity),AuthorizedMcpAction(surface.identity,aid,"call-1","logs.search",good.arguments,good.argument_bytes)):
   with self.assertRaises(ProviderError): c.execute(action,d)
   self.assertEqual(c.next_id,before)
  c.close(d,suppress=True)
 def test_authorized_snapshot_is_immutable_and_valid_action_writes_once(self):
  c=client(); d=deadline(c); c.initialize_and_capture(d); source={"query":"original"}; action=c.authorize(proposal("call-1").action_identity,"call-1","logs.search",source); source["query"]="mutated"
  response=c.execute(action,d); self.assertEqual(response.request_id,3); self.assertEqual(action.arguments["query"],"original"); self.assertEqual(c.next_id,4); c.close(d,suppress=True)

class CorrelationAndCancellationTests(unittest.TestCase):
 def test_unsolicited_response_fails_closed(self): self._assert_bad("unsolicited")
 def test_future_response_fails_closed(self): self._assert_bad("future_id")
 def test_duplicate_completed_response_fails_closed(self): self._assert_bad("duplicate_completed")
 def _assert_bad(self,case):
  c=client(case); out=Orchestrator(c,provider(),limits=c.limits).run(req()); self.assertEqual(out.outcome,"failed"); self.assertIsNone(c.process)
 def test_cancellation_during_provider_reaps_child(self):
  import threading
  token=CancellationToken(); c=client(); trigger=threading.Thread(target=lambda:(time.sleep(.02),token.cancel()))
  trigger.start(); out=Orchestrator(c,provider(ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")),delay_ms=200),cancellation=token).run(req()); trigger.join()
  self.assertEqual(out.outcome,"cancelled"); self.assertIsNone(c.process); self.assertIn(b'"cancelled"',out.transcript)
 def test_cancellation_during_mcp_wait_skips_later_actions(self):
  import threading
  token=CancellationToken(); c=client("delay"); trigger=threading.Thread(target=lambda:(time.sleep(.05),token.cancel()))
  trigger.start(); out=Orchestrator(c,provider((proposal("call-1","a"),proposal("call-2","b"))),cancellation=token).run(req()); trigger.join()
  self.assertEqual(out.outcome,"cancelled"); self.assertEqual(len(out.execution_order),0); self.assertIn(b'"skipped"',out.transcript); self.assertIsNone(c.process)

class AtMostOnceTests(unittest.TestCase):
 def test_changed_content_reusing_call_id_in_one_response_is_rejected_before_write(self):
  c=client(); out=Orchestrator(c,provider((proposal("call-1","a"),proposal("call-1","b")))).run(req())
  self.assertEqual(out.outcome,"duplicate"); self.assertEqual(len(out.execution_order),0); self.assertIn(b'"proposal_duplicate"',out.transcript); self.assertIsNone(c.process)
 def test_identical_content_under_different_call_ids_is_rejected_before_write(self):
  c=client(); out=Orchestrator(c,provider((proposal("call-1","a"),proposal("call-2","a")))).run(req())
  self.assertEqual(out.outcome,"duplicate"); self.assertEqual(len(out.execution_order),0); self.assertIsNone(c.process)
 def test_completed_call_id_replay_in_later_turn_is_rejected(self):
  c=client(); out=Orchestrator(c,provider((proposal("call-1","a"),),(proposal("call-1","b"),))).run(req())
  self.assertEqual(out.outcome,"duplicate"); self.assertEqual(len(out.execution_order),1); self.assertIsNone(c.process)

class EvidenceAndTranscriptTests(unittest.TestCase):
 def test_closed_result_variants_fail(self):
  for case in ("malformed_result","result_missing_content","result_wrong_content","result_unknown_block","result_unknown_type","result_missing_text","result_wrong_text","result_oversized_text","result_many_blocks","result_structured"):
   c=client(case); out=Orchestrator(c,provider((proposal("call-1"),)),limits=c.limits).run(req()); self.assertEqual(out.outcome,"failed",case); self.assertIsNone(c.process)
 def test_serial_probe_reports_one_active_call_in_provider_order(self):
  c=client("serial_probe"); out=Orchestrator(c,provider((proposal("call-1","a"),proposal("call-2","b")),ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done")))).run(req())
  self.assertEqual(len(out.execution_order),2); self.assertNotEqual(out.execution_order[0],out.execution_order[1]); self.assertIn("maxActive=1",str(out.evidence))
 def test_transcript_reserves_terminal_without_erasing_prefix(self):
  import json
  terminal={"schemaVersion":2,"events":[{"event":"process_start","metadata":{}},{"event":"transcript_limit","metadata":{}}],"limited":True}
  limit=len(json.dumps(terminal,sort_keys=True,separators=(",",":")).encode())
  transcript=Phase10Transcript(replace(DEFAULT_LIMITS,transcript_bytes=limit)); transcript.add("process_start"); prefix=transcript.to_json_bytes(); transcript.add("initialize_request"); exhausted=transcript.to_json_bytes()
  self.assertIn(b'"process_start"',exhausted); self.assertEqual(exhausted.count(b'"transcript_limit"'),1); self.assertLessEqual(len(exhausted),limit); self.assertEqual(parse_phase_10_2_transcript(exhausted),parse_phase_10_2_transcript(exhausted)); self.assertNotEqual(prefix,exhausted)
if __name__=="__main__": unittest.main(verbosity=2)
