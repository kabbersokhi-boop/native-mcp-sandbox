#!/usr/bin/env python3
"""Focused deterministic tests for the Phase 10.2 offline orchestrator."""
from __future__ import annotations
import os, sys, unittest
from dataclasses import replace
ROOT=os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0, os.path.join(ROOT,"agent"))
from native_mcp_agent.contracts import (ProviderMessage, ProviderRequest, ProviderToolCallProposal, RequestCorrelationId, ToolCallId, MessageRole, ProviderFinalMessage)
from native_mcp_agent.errors import ProviderError
from native_mcp_agent.limits import DEFAULT_LIMITS
from native_mcp_agent.mcp_orchestrator import McpStdioClient, Orchestrator, capture_tool_surface

CHILD=os.path.join(ROOT,"tests","fake_mcp_stdio_child.py")
def client(case="normal", **kwargs): return McpStdioClient(sys.executable,(CHILD,case), child_allowlist=("LANG",), parent_environment={"LANG":"C","SECRET_SENTINEL":"nope","HTTP_PROXY":"bad"}, **kwargs)
def request(): return ProviderRequest("fake",(ProviderMessage(MessageRole.USER,"investigate"),),(),32,RequestCorrelationId("req-10-2"))
def proposal(n, q="one"): return ProviderToolCallProposal(ToolCallId(n),"logs.search",{"query":q})

class ClientTests(unittest.TestCase):
 def tearDown(self):
  if hasattr(self,"c"): self.c.close()
 def test_minimal_environment_and_capture(self):
  self.c=client(); surface=self.c.initialize_and_capture(); self.assertEqual(self.c.environment,{"LANG":"C"}); self.assertEqual(len(surface.tools),2); self.assertEqual(len(surface.identity),64)
 def test_bad_messages_and_output_are_rejected(self):
  for case in ("malformed","duplicate_keys","wrong_id","flood"):
   with self.subTest(case=case):
    self.c=client(case)
    with self.assertRaises(ProviderError): self.c.initialize_and_capture()
    self.c.close(); del self.c
 def test_exact_tool_schema_contract(self):
  good={"tools":[{"name":"x","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":False}}]}
  self.assertEqual(len(capture_tool_surface(good).tools),1)
  bad={"tools":[{"name":"x","inputSchema":{"type":"object","properties":{},"additionalProperties":True}}]}
  with self.assertRaises(ProviderError): capture_tool_surface(bad)

class OrchestrationTests(unittest.TestCase):
 def run_it(self, responses):
  c=client(); self.addCleanup(c.close); iterator=iter(responses)
  return Orchestrator(c,context="fixture").run(lambda _r,_e: next(iterator),request())
 def test_serial_order_and_evidence(self):
  out=self.run_it([(proposal("call-1","a"),proposal("call-2","b")),ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))])
  self.assertEqual(out.outcome,"final"); self.assertEqual(len(out.execution_order),2); self.assertEqual(len(out.evidence),2)
 def test_at_most_once_provider_id_and_content(self):
  out=self.run_it([(proposal("call-1"),), (proposal("call-2"),)])
  self.assertEqual(out.outcome,"duplicate")
 def test_failure_stops_later_proposals(self):
  c=client("exit"); self.addCleanup(c.close)
  out=Orchestrator(c,context="fixture").run(lambda _r,_e: (proposal("call-1","a"),proposal("call-2","b")),request())
  self.assertEqual(out.outcome,"failed"); self.assertEqual(len(out.execution_order),0)
 def test_timeout_and_ambiguous_exit(self):
  limits=replace(DEFAULT_LIMITS,mcp_call_timeout_ms=20); c=client("delay",limits=limits); self.addCleanup(c.close)
  with self.assertRaises(ProviderError):
   c.initialize_and_capture(); c.call("logs.search",{"query":"x"})
 def test_transcript_is_deterministic_and_secret_free(self):
  a=self.run_it([ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))]).transcript
  b=self.run_it([ProviderFinalMessage(ProviderMessage(MessageRole.ASSISTANT,"done"))]).transcript
  self.assertEqual(a,b); self.assertNotIn(b"SECRET_SENTINEL",a)

if __name__ == "__main__": unittest.main(verbosity=2)
