#!/usr/bin/env python3
"""Offline credential-free adversarial MCP stdio fixture."""

from __future__ import annotations
import json
import signal
import sys
import time
from typing import Any


PROTOCOL_VERSION = "2025-11-25"
scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
listed = 0
active = 0
maximum = 0
UNIQUE_SENTINELS = (
    "API_KEY_ASSURANCE_UNIQUE",
    "Authorization: Bearer TOKEN_ASSURANCE_UNIQUE",
    "proxy://user:pass@host",
    "SECRET_STORE_ASSURANCE_UNIQUE",
    "/absolute/agent-assurance/sentinel",
    "pid=424242",
    "--command-secret=CMD_ASSURANCE",
)
if scenario == "ignore_shutdown":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if scenario == "delayed_start":
    time.sleep(0.2)
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
    "additionalProperties": False,
}

tools = [
    {
        "name": "logs.search",
        "title": "Search synthetic logs",
        "description": "synthetic",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 32}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "outputSchema": _OUTPUT_SCHEMA,
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
        "execution": {"taskSupport": "forbidden"},
    },
    {
        "name": "logs.count",
        "title": "Count synthetic logs",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "outputSchema": _OUTPUT_SCHEMA,
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
        "execution": {"taskSupport": "forbidden"},
    },
]


def emit(value: Any) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def result(request: dict[str, Any], value: Any) -> None:
    emit({"jsonrpc": "2.0", "id": request["id"], "result": value})


def successful_tool_result(message: str) -> dict[str, Any]:
    structured = {"message": message}
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured, separators=(",", ":")),
            }
        ],
        "isError": False,
        "structuredContent": structured,
    }


for line in sys.stdin:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        break

    method = request.get("method")
    if scenario == "malformed" and method == "initialize":
        sys.stdout.write("{bad\n")
        sys.stdout.flush()
        continue
    if scenario == "duplicate_keys" and method == "initialize":
        sys.stdout.write('{"jsonrpc":"2.0","id":1,"id":1,"result":{}}\n')
        sys.stdout.flush()
        continue
    if scenario == "wrong_id" and method == "initialize":
        emit({"jsonrpc": "2.0", "id": 999, "result": {}})
        continue
    if scenario == "unsolicited" and method == "initialize":
        emit({"jsonrpc": "2.0", "id": 0, "result": {}})
        continue
    if scenario == "future_id" and method == "initialize":
        emit({"jsonrpc": "2.0", "id": 2, "result": {}})
        continue
    if scenario == "truncated" and method == "initialize":
        sys.stdout.write('{"jsonrpc":"2.0"')
        sys.stdout.flush()
        sys.exit(0)
    if scenario == "oversized" and method == "initialize":
<<<<<<< HEAD
        sys.stdout.write('{"jsonrpc":"2.0","id":1,"result":"' + ("x" * 70000) + '"}\n')
=======
        sys.stdout.write(
            '{"jsonrpc":"2.0","id":1,"result":"'
            + ("x" * 70000)
            + '"}\n'
        )
>>>>>>> f3f7fe2 (test: model the real MCP tool and result schemas [skip ci])
        sys.stdout.flush()
        continue
    if scenario == "flood" and method == "initialize":
        sys.stdout.write("x" * 200000)
        sys.stdout.flush()
        continue
    if scenario == "exit" and method == "tools/call":
        sys.exit(0)
    if method == "initialize":
        if scenario == "delayed_initialize":
            time.sleep(0.2)
        result(
            request,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "serverInfo": {"name": "fake-mcp", "version": "0.11.0"},
            },
        )
    elif method == "tools/list":
        if scenario == "duplicate_completed":
            emit({"jsonrpc": "2.0", "id": 1, "result": {}})
            continue
        if scenario == "delayed_list":
            time.sleep(0.2)
        listed_tools = tools if scenario != "changing_tools" or listed == 0 else tools[:1]
        result(request, {"tools": listed_tools})
        listed += 1
    elif method == "tools/call":
        active += 1
        maximum = max(maximum, active)
        if scenario == "delay":
            time.sleep(0.2)
        active -= 1
        if scenario == "malformed_result":
            result(request, {"content": [{"type": "text"}], "unknown": 1})
        elif scenario == "result_missing_content":
            result(request, {})
        elif scenario == "result_wrong_content":
            result(request, {"content": {}})
        elif scenario == "result_unknown_block":
            result(
                request,
                {"content": [{"type": "text", "text": "x", "extra": 1}]},
            )
        elif scenario == "result_unknown_type":
            result(request, {"content": [{"type": "resource", "text": "x"}]})
        elif scenario == "result_missing_text":
            result(request, {"content": [{"type": "text"}]})
        elif scenario == "result_wrong_text":
            result(request, {"content": [{"type": "text", "text": 1}]})
        elif scenario == "result_oversized_text":
            result(
                request,
                {"content": [{"type": "text", "text": "x" * 9000}]},
            )
        elif scenario == "result_many_blocks":
            result(
                request,
                {"content": [{"type": "text", "text": "x"} for _ in range(33)]},
            )
        elif scenario == "result_structured":
            result(
                request,
                {
                    "content": [{"type": "text", "text": "{}"}],
                    "isError": False,
                    "structuredContent": {},
                },
            )
        elif scenario == "secret_result":
            result(
                request,
                successful_tool_result(
                    "Authorization: Bearer SECRET_SENTINEL /tmp/host pid=123"
                ),
            )
        elif scenario == "unique_secret_output":
            sys.stderr.write(" ".join(UNIQUE_SENTINELS) + "\n")
            sys.stderr.flush()
            result(
                request,
                {
                    "content": [
                        {"type": "text", "text": " ".join(UNIQUE_SENTINELS)}
                    ],
                    "isError": True,
                },
            )
        elif scenario == "unique_secret_error":
            sys.stderr.write(" ".join(UNIQUE_SENTINELS) + "\n")
            sys.stderr.flush()
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {
                        "code": -32000,
                        "message": " ".join(UNIQUE_SENTINELS),
                    },
                }
            )
        elif scenario == "serial_probe":
            result(request, successful_tool_result(f"maxActive={maximum}"))
        else:
            result(request, successful_tool_result("synthetic"))
if scenario == "ignore_shutdown":
    while True:
        time.sleep(0.1)
