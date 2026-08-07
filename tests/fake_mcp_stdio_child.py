#!/usr/bin/env python3
"""Offline credential-free adversarial MCP stdio fixture."""
import json, signal, sys, time
scenario=sys.argv[1] if len(sys.argv)>1 else "normal"; listed=0; active=0; maximum=0
if scenario=="ignore_shutdown": signal.signal(signal.SIGTERM, signal.SIG_IGN)
if scenario=="delayed_start": time.sleep(.2)
tools=[{"name":"logs.search","description":"synthetic","inputSchema":{"type":"object","properties":{"query":{"type":"string","maxLength":32}},"required":["query"],"additionalProperties":False}}, {"name":"logs.count","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":False}}]
def emit(v): sys.stdout.write(json.dumps(v,separators=(",",":"))+"\n"); sys.stdout.flush()
def result(req,v): emit({"jsonrpc":"2.0","id":req["id"],"result":v})
for line in sys.stdin:
 try: req=json.loads(line)
 except json.JSONDecodeError: break
 method=req.get("method")
 if scenario=="malformed" and method=="initialize": sys.stdout.write("{bad\n"); sys.stdout.flush(); continue
 if scenario=="duplicate_keys" and method=="initialize": sys.stdout.write('{"jsonrpc":"2.0","id":1,"id":1,"result":{}}\n'); sys.stdout.flush(); continue
 if scenario=="wrong_id" and method=="initialize": emit({"jsonrpc":"2.0","id":999,"result":{}}); continue
 if scenario=="unsolicited" and method=="initialize": emit({"jsonrpc":"2.0","id":0,"result":{}}); continue
 if scenario=="future_id" and method=="initialize": emit({"jsonrpc":"2.0","id":2,"result":{}}); continue
 if scenario=="truncated" and method=="initialize": sys.stdout.write('{"jsonrpc":"2.0"'); sys.stdout.flush(); sys.exit(0)
 if scenario=="oversized" and method=="initialize": sys.stdout.write('{"jsonrpc":"2.0","id":1,"result":"'+("x"*70000)+'"}\n'); sys.stdout.flush(); continue
 if scenario=="flood" and method=="initialize": sys.stdout.write("x"*200000); sys.stdout.flush(); continue
 if scenario=="exit" and method=="tools/call": sys.exit(0)
 if method=="initialize":
  if scenario=="delayed_initialize": time.sleep(.2)
  result(req,{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{}})
 elif method=="tools/list":
  if scenario=="duplicate_completed": emit({"jsonrpc":"2.0","id":1,"result":{}}); continue
  if scenario=="delayed_list": time.sleep(.2)
  result(req,{"tools":tools if scenario!="changing_tools" or listed==0 else tools[:1]}); listed+=1
 elif method=="tools/call":
  active+=1; maximum=max(maximum,active)
  if scenario=="delay": time.sleep(.2)
  active-=1
  if scenario=="malformed_result": result(req,{"content":[{"type":"text"}],"unknown":1})
  elif scenario=="result_missing_content": result(req,{})
  elif scenario=="result_wrong_content": result(req,{"content":{}})
  elif scenario=="result_unknown_block": result(req,{"content":[{"type":"text","text":"x","extra":1}]})
  elif scenario=="result_unknown_type": result(req,{"content":[{"type":"resource","text":"x"}]})
  elif scenario=="result_missing_text": result(req,{"content":[{"type":"text"}]})
  elif scenario=="result_wrong_text": result(req,{"content":[{"type":"text","text":1}]})
  elif scenario=="result_oversized_text": result(req,{"content":[{"type":"text","text":"x"*9000}]})
  elif scenario=="result_many_blocks": result(req,{"content":[{"type":"text","text":"x"} for _ in range(33)]})
  elif scenario=="result_structured": result(req,{"content":[{"type":"text","text":"x"}],"structuredContent":{}})
  elif scenario=="secret_result": result(req,{"content":[{"type":"text","text":"Authorization: Bearer SECRET_SENTINEL /tmp/host pid=123"}]})
  elif scenario=="serial_probe": result(req,{"content":[{"type":"text","text":f"maxActive={maximum}"}]})
  else: result(req,{"content":[{"type":"text","text":"synthetic"}]})
