#!/usr/bin/env python3
"""Credential-free scripted stdio fixture for Phase 10.2."""
import json, os, sys, time

scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
calls = 0
tools = [{"name":"logs.search","description":"synthetic","inputSchema":{"type":"object","properties":{"query":{"type":"string","maxLength":32}},"required":["query"],"additionalProperties":False}}, {"name":"logs.count","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":False}}]
def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",",":")) + "\n"); sys.stdout.flush()
def result(request, payload): emit({"jsonrpc":"2.0","id":request["id"],"result":payload})
for line in sys.stdin:
    try: req=json.loads(line)
    except json.JSONDecodeError: break
    method=req.get("method")
    if scenario == "exit" and method == "tools/call": sys.exit(0)
    if scenario == "malformed" and method == "initialize": sys.stdout.write("{bad\n"); sys.stdout.flush(); continue
    if scenario == "duplicate_keys" and method == "initialize": sys.stdout.write('{"jsonrpc":"2.0","id":1,"id":1,"result":{}}\n'); sys.stdout.flush(); continue
    if scenario == "wrong_id" and method == "initialize": emit({"jsonrpc":"2.0","id":999,"result":{}}); continue
    if scenario == "flood" and method == "initialize": sys.stdout.write("x" * 200000); sys.stdout.flush(); continue
    if method == "initialize": result(req,{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{}})
    elif method == "tools/list":
        result(req,{"tools": tools if scenario != "changing_tools" or calls == 0 else tools[:1]}); calls += 1
    elif method == "tools/call":
        if scenario == "delay": time.sleep(0.2)
        result(req,{"content":[{"type":"text","text":"synthetic"}]})
