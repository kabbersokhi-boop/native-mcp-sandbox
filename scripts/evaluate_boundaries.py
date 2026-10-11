#!/usr/bin/env python3
"""Generate native enforcement results from direct, reproducible MCP requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from stdio_harness import exchange

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from native_mcp_agent.demo import DemoFailure, run_demo, write_elf
from native_mcp_agent.errors import ProviderError


def wire(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def lifecycle() -> bytes:
    return wire({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "boundary-evaluation", "version": "1"},
    }}) + wire({"jsonrpc": "2.0", "method": "notifications/initialized"})


def call(name: str, arguments: dict) -> bytes:
    return wire({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": name, "arguments": arguments}})


def classify(response: dict) -> str:
    if "error" in response:
        return f"rpc:{response['error']['code']}"
    result = response["result"]
    if result.get("isError"):
        return "tool:" + json.loads(result["content"][0]["text"])["error"]["code"]
    return "allowed"


def evaluate(server: Path, output: Path, *, extended: bool = False) -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix="nms-evaluation-") as directory:
        workspace = Path(directory)
        root = workspace / "evidence"
        root.mkdir(mode=0o700)
        (root / "application.log").write_text("INC-042 healthy\n")
        (workspace / "outside.txt").write_text("OUTSIDE_POLICY_SENTINEL\n")
        (root / "escape").symlink_to(workspace / "outside.txt")
        (root / "magic").symlink_to("/proc/self/fd/0")
        write_elf(root / "sample.elf", 62)
        policy = workspace / "policy.json"
        policy.write_bytes(wire({"version": 2, "roots": [
            {"name": "evidence", "path": str(root), "maxFileBytes": 65536}],
            "processes": [{"name": "server", "pid": "self"}]}))
        base = {"root": "evidence", "path": "application.log", "query": "INC-042"}
        cases = [
            ("allowed-log", "logs.search", base, "allowed"),
            ("allowed-tail", "logs.tail", {"root": "evidence", "path": "application.log"}, "allowed"),
            ("allowed-elf", "elf.inspect", {"root": "evidence", "path": "sample.elf"}, "allowed"),
            ("allowed-process", "proc.memory", {"process": "server"}, "allowed"),
            ("parent-traversal", "logs.search", {**base, "path": "../outside.txt"}, "tool:invalid_relative_path"),
            ("absolute-path", "logs.search", {**base, "path": "/etc/passwd"}, "tool:invalid_relative_path"),
            ("symlink-escape", "logs.search", {**base, "path": "escape"}, "tool:resolution_denied"),
            ("magic-link", "logs.search", {**base, "path": "magic"}, "tool:resolution_denied"),
            ("unknown-root", "logs.search", {**base, "root": "unapproved"}, "tool:unknown_root"),
            ("unknown-process", "proc.memory", {"process": "unapproved"}, "tool:unknown_process"),
            ("raw-pid", "proc.memory", {"process": "server", "pid": 1}, "tool:invalid_arguments"),
            ("unknown-field", "logs.search", {**base, "recursive": True}, "tool:invalid_arguments"),
            ("invented-shell", "shell.exec", {"command": "echo denied"}, "rpc:-32602"),
        ]
        command = [str(server.resolve()), "--policy-config", str(policy)]
        for name, tool, arguments, expected in cases:
            try:
                observation = exchange(command, lifecycle() + call(tool, arguments))
                messages = [json.loads(item) for item in observation.stdout.splitlines()]
                responses = [item for item in messages if item.get("id") == 2]
                actual = classify(responses[0]) if len(responses) == 1 else "invalid-response-set"
                valid = observation.status == 0 and not observation.stderr
                valid = valid and len(messages) == 2 and messages[0].get("id") == 1
                valid = valid and "result" in messages[0]
                valid = valid and b"OUTSIDE_POLICY_SENTINEL" not in observation.stdout
                if actual == "allowed":
                    structured = responses[0]["result"].get("structuredContent", {})
                    valid = valid and bool(structured)
                    if tool == "proc.memory":
                        valid = valid and structured.get("pidfdPinned") is True
                results.append({"id": name, "layer": "native", "tool": tool,
                    "arguments": arguments, "expected": expected, "actual": actual,
                    "passed": valid and actual == expected,
                    "response": responses[0] if responses and actual != "allowed" else None,
                    "source": "src/file_policy.cpp" if tool.startswith("logs.") else "src/tool_service.cpp"})
            except (OSError, ValueError, KeyError, TimeoutError, subprocess.TimeoutExpired) as error:
                results.append({"id": name, "layer": "native", "expected": expected,
                    "actual": type(error).__name__, "passed": False})
        protocol_cases = [
            ("duplicate-json-key", b'{"jsonrpc":"2.0","id":2,"id":3,"method":"ping"}\n', "rpc:-32600"),
            ("null-request-id", wire({"jsonrpc": "2.0", "id": None, "method": "ping"}), "rpc:-32600"),
            ("oversized-request", b"x" * (1024 * 1024 + 1) + b"\n", "rpc:-32001"),
        ]
        for name, payload, expected in protocol_cases:
            try:
                observation = exchange(command, payload)
                messages = [json.loads(item) for item in observation.stdout.splitlines()]
                actual = classify(messages[0]) if len(messages) == 1 else "invalid-response-set"
                results.append({"id": name, "layer": "native protocol", "expected": expected,
                    "actual": actual, "passed": actual == expected and observation.status == 0,
                    "source": "src/server.cpp"})
            except (OSError, ValueError, KeyError, TimeoutError, subprocess.TimeoutExpired) as error:
                results.append({"id": name, "layer": "native protocol", "expected": expected,
                    "actual": type(error).__name__, "passed": False})
        try:
            hostile = run_demo(server, "hostile", output / "hostile")
            results.append({"id": "hostile-proposals", "layer": "native + Python (separate decisions)",
                "expected": "boundary-held", "actual": hostile["result"],
                "passed": hostile["result"] == "boundary-held",
                "artifact": "hostile/report.json", "source": "agent/native_mcp_agent/mcp_orchestrator.py"})
        except (DemoFailure, ProviderError, OSError) as error:
            results.append({"id": "hostile-proposals", "layer": "native + Python",
                "expected": "boundary-held", "actual": type(error).__name__, "passed": False})
    if extended:
        suites = [
            ("protocol-sequences", [str(server.parent / "native_mcp_protocol_tests")]),
            ("scheduler-unit", [str(server.parent / "native_mcp_orchestration_tests")]),
            ("scheduler-stress", [str(server.parent / "native_mcp_orchestration_stress_tests")]),
            ("native-security", [str(server.parent / "native_mcp_security_regression_tests")]),
            ("replay-and-correlation", [sys.executable, str(ROOT / "tests/mcp_orchestration_tests.py")]),
            ("transcript-and-fabrication", [sys.executable, str(ROOT / "tests/adversarial_agent_tests.py")]),
            ("transport-liveness", [sys.executable, str(ROOT / "tests/transport_liveness_tests.py"), "--server", str(server.resolve())]),
            ("unavailable-controls", [sys.executable, str(ROOT / "tests/strict_control_tests.py"), "--server", str(server.resolve()), "--helper", str(server.parent / "native_mcp_unavailable_control")]),
        ]
        (output / "suites").mkdir(parents=True, exist_ok=True)
        for name, command in suites:
            try:
                observation = exchange(command, b"", timeout=30)
                record = observation.stdout + observation.stderr
                artifact = f"suites/{name}.txt"
                (output / artifact).write_bytes(record)
                results.append({"id": name, "layer": "named regression suite", "expected": "exit:0",
                    "actual": f"exit:{observation.status}", "passed": observation.status == 0,
                    "artifact": artifact, "sha256": hashlib.sha256(record).hexdigest()})
            except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as error:
                results.append({"id": name, "layer": "named regression suite", "expected": "exit:0",
                    "actual": type(error).__name__, "passed": False})
    for case in results:
        case["attackerControl"] = (
            "Synthetic proposal and evidence text" if case["id"] == "hostile-proposals" else
            "Regression-specific inputs and scheduling; inspect the named suite" if case["layer"] == "named regression suite" else
            "Raw stdio JSON-RPC bytes; Python proposal validation bypassed")
        case["residualLimitation"] = (
            "Scripted proposal enforcement, not live-model injection susceptibility" if case["id"] == "hostile-proposals" else
            "Finite regression coverage, not an exhaustive proof or kernel sandbox")
    report = {"schemaVersion": 1, "passed": all(item["passed"] for item in results),
              "environment": {"kernel": platform.release(), "architecture": platform.machine()},
              "binarySha256": hashlib.sha256(server.read_bytes()).hexdigest(),
              "cases": results,
              "limits": ["Synthetic boundary cases; not a universal prompt-injection score.",
                         "Named suites aggregate their own assertions; a suite is not counted as one attack.",
                         "No unavailable control is silently classified as a successful rejection."]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    rows = ["# Boundary evaluation", "", "| Case | Layer | Expected | Observed | Pass |",
            "| --- | --- | --- | --- | --- |"]
    rows.extend(f"| {case['id']} | {case['layer']} | {case['expected']} | {case['actual']} | {case['passed']} |"
                for case in results)
    rows.extend(["", *report["limits"], ""])
    (output / "evaluation.md").write_text("\n".join(rows))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("build/boundary-evaluation"))
    parser.add_argument("--extended", action="store_true")
    arguments = parser.parse_args()
    result = evaluate(arguments.server.resolve(), arguments.output, extended=arguments.extended)
    for case in result["cases"]:
        print(f"{'PASS' if case['passed'] else 'FAIL'} {case['id']}: {case['actual']}")
    raise SystemExit(0 if result["passed"] else 1)
