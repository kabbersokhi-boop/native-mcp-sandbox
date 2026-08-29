#!/usr/bin/env python3
"""Run the real server demos and verify the native-agent MCP contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


SOURCE_DIR = Path(__file__).resolve().parents[1]
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from agent.native_mcp_agent.contracts import LocalActionIdentity  # noqa: E402
from agent.native_mcp_agent.mcp_orchestrator import (  # noqa: E402
    Deadline,
    MCP_PROTOCOL_VERSION,
    McpStdioClient,
)


EXPECTED_CONCLUSION = "healthy_final_state_confirmed"
FORBIDDEN_REPORT_KEYS = {
    "pid",
    "uid",
    "pageSizeBytes",
    "status",
    "statm",
    "smapsRollup",
    "smapsRollupError",
    "vmPeakBytes",
    "vmSizeBytes",
    "vmHwmBytes",
    "vmRssBytes",
    "rssAnonBytes",
    "rssFileBytes",
    "rssShmemBytes",
    "vmDataBytes",
    "vmStackBytes",
    "vmExecutableBytes",
    "vmLibraryBytes",
    "vmPageTableBytes",
    "vmSwapBytes",
    "hugetlbBytes",
    "virtualBytes",
    "residentBytes",
    "sharedBytes",
    "textBytes",
    "dataAndStackBytes",
    "rssBytes",
    "pssBytes",
    "pssAnonBytes",
    "pssFileBytes",
    "pssShmemBytes",
    "sharedCleanBytes",
    "sharedDirtyBytes",
    "privateCleanBytes",
    "privateDirtyBytes",
    "referencedBytes",
    "anonymousBytes",
    "swapBytes",
    "swapPssBytes",
    "lockedBytes",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def run_demo(demo: Path, server: Path, fixture: Path, output_dir: Path) -> None:
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(demo),
                "--server",
                str(server),
                "--fixture",
                str(fixture),
                "--output-dir",
                str(output_dir),
            ],
            check=False,
            capture_output=True,
            timeout=30.0,
            text=True,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        fail("the demonstration test timed out")
    if result.returncode != 0:
        fail(f"the demonstration failed: {result.stdout}{result.stderr}")


def check_report_safety(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"{label} is not valid JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{label} is not a JSON object")
    inspect_report_value(value, label)
    if value.get("conclusion") != EXPECTED_CONCLUSION:
        fail(f"{label} has an unexpected conclusion")
    if value.get("security") != {
        "legacyFlagsPassed": False,
        "strictOpenat2": True,
        "strictPidfdPinning": True,
    }:
        fail(f"{label} has unexpected strict-mode evidence")
    check_text_safety(data.decode("utf-8"), label)
    return value


def inspect_report_value(value: object, label: str, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_REPORT_KEYS:
                fail(f"{label} contains forbidden field {path}.{key}")
            inspect_report_value(child, label, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            inspect_report_value(child, label, f"{path}[{index}]")


def check_text_safety(text: str, label: str) -> None:
    forbidden = [
        (r"(?:^|[^A-Za-z])(?:pid|uid)\s*[:=]\s*\d+", "raw process identity"),
        (r"/tmp/|native-mcp-investigation-", "temporary path"),
        (r"0x[0-9A-Fa-f]{4,}", "runtime address"),
        (r"20\d\d-\d\d-\d\d[T ]\d\d:\d\d:\d\d", "runtime timestamp"),
    ]
    for pattern, description in forbidden:
        if re.search(pattern, text):
            fail(f"{label} contains {description}")


def expect_forbidden_field_rejected(
    report: dict[str, object], field: str, value: object
) -> None:
    mutated = json.loads(json.dumps(report))
    mutated["evidence"][0]["finding"][field] = value  # type: ignore[index]
    try:
        check_report_safety(json.dumps(mutated).encode("utf-8"), f"field {field}")
    except AssertionError:
        return
    fail(f"field {field} was accepted in a report")


def run_output_flood_negative_test(demo: Path, server: Path, fixture: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="native-mcp-demo-flood-") as directory:
        output_dir = Path(directory)
        fake = output_dir / "fake-output-server.py"
        fake.write_text(
            "#!" + sys.executable + "\n"
            "import sys\n"
            "sys.stdout.buffer.write(b'x' * (256 * 1024 + 1))\n"
            "sys.stdout.flush()\n",
            encoding="utf-8",
            newline="\n",
        )
        os.chmod(fake, 0o700)
        (output_dir / "report.json").write_text("stale", encoding="utf-8")
        (output_dir / "report.md").write_text("stale", encoding="utf-8")
        started = time.monotonic()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(demo),
                    "--server",
                    str(fake),
                    "--fixture",
                    str(fixture),
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                timeout=10.0,
                text=True,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            fail("the output-flood negative test exceeded its prompt-failure timeout")
        elapsed = time.monotonic() - started
        if result.returncode == 0:
            fail("the output-flood executable was accepted")
        if elapsed >= 5.0:
            fail(
                f"the output-flood executable failed too slowly: {elapsed:.2f} seconds"
            )
        if (output_dir / "report.json").exists() or (output_dir / "report.md").exists():
            fail("a failed output-flood run left a stale report")


def run_real_agent_server_contract(server: Path) -> None:
    """Exercise the actual Python MCP client against the actual C++ server."""
    with tempfile.TemporaryDirectory(prefix="native-mcp-agent-contract-") as directory:
        root = Path(directory)
        log = root / "application.log"
        log.write_text(
            "INFO boot\nERROR INC-042 synthetic failure\nINFO recovered\n",
            encoding="utf-8",
            newline="\n",
        )
        many = root / "many.log"
        many.write_text(
            "".join(f"ERROR INC-050 {chr(1) * 500}\n" for _ in range(50)),
            encoding="utf-8",
            newline="\n",
        )
        policy = root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {
                            "name": "evidence",
                            "path": str(root),
                            "maxFileBytes": 64 * 1024,
                        }
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.chmod(log, 0o600)
        os.chmod(many, 0o600)
        os.chmod(policy, 0o600)

        client = McpStdioClient(
            str(server),
            ("--policy-config", str(policy)),
            child_allowlist=("LANG", "LC_ALL"),
            parent_environment={"LANG": "C", "LC_ALL": "C"},
        )
        deadline = Deadline(time.monotonic() + 5.0, time.monotonic)
        try:
            surface = client.initialize_and_capture(deadline)
            if client.last_initialize is None:
                fail("the real agent did not retain the initialize response")
            negotiated = client.last_initialize.result.get("protocolVersion")
            if negotiated != MCP_PROTOCOL_VERSION:
                fail("the real server and real agent negotiated different MCP revisions")

            names = tuple(tool.name for tool in surface.tools)
            if names != ("logs.search", "logs.tail", "elf.inspect"):
                fail(f"the real agent captured an unexpected tool surface: {names}")
            if surface.output_schemas.get("logs.search") is None:
                fail("the real agent did not capture logs.search outputSchema")

            action = client.authorize(
                LocalActionIdentity("0" * 32),
                "call-1",
                "logs.search",
                {
                    "root": "evidence",
                    "path": "application.log",
                    "query": "INC-042",
                    "caseSensitive": True,
                    "maxMatches": 4,
                },
            )
            response = client.execute(action, deadline)
            structured = response.result.get("structuredContent")
            if not isinstance(structured, dict):
                fail("the real agent rejected or lost structuredContent")
            if structured.get("root") != "evidence":
                fail("the validated structured result has an unexpected root")
            matches = structured.get("matches")
            if not isinstance(matches, tuple) or len(matches) != 1:
                fail("the validated structured result has an unexpected match count")
            if not isinstance(matches[0], dict) or matches[0].get("line") != 2:
                fail("the validated structured result has an unexpected match")

            large_action = client.authorize(
                LocalActionIdentity("1" * 32),
                "call-2",
                "logs.search",
                {
                    "root": "evidence",
                    "path": "many.log",
                    "query": "INC-050",
                    "caseSensitive": True,
                    "maxMatches": 50,
                },
            )
            large_response = client.execute(large_action, deadline)
            large_structured = large_response.result.get("structuredContent")
            if (not isinstance(large_structured, dict) or
                    not isinstance(large_structured.get("matches"), tuple) or
                    len(large_structured["matches"]) != 50):
                fail("the real agent rejected a native 50-match structured result")
            if large_response.byte_count <= 64 * 1024:
                fail("the native large-result fixture did not exercise the MCP evidence byte bound")
        finally:
            client.close(deadline, suppress=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    source_dir = SOURCE_DIR
    demo = source_dir / "scripts" / "run_agent_investigation_demo.py"
    fixture = source_dir / "demo" / "investigation" / "application.log"
    expected_json = source_dir / "demo" / "investigation" / "expected-report.json"
    expected_markdown = source_dir / "demo" / "investigation" / "expected-report.md"
    with (
        tempfile.TemporaryDirectory(prefix="native-mcp-demo-test-") as first,
        tempfile.TemporaryDirectory(prefix="native-mcp-demo-test-") as second,
    ):
        first_dir = Path(first)
        second_dir = Path(second)
        run_demo(demo, arguments.server.resolve(), fixture, first_dir)
        run_demo(demo, arguments.server.resolve(), fixture, second_dir)
        first_json = (first_dir / "report.json").read_bytes()
        second_json = (second_dir / "report.json").read_bytes()
        first_markdown = (first_dir / "report.md").read_bytes()
        second_markdown = (second_dir / "report.md").read_bytes()
        if first_json != second_json:
            fail("JSON reports differ between separate runs")
        if first_markdown != second_markdown:
            fail("Markdown reports differ between separate runs")
        if first_json != expected_json.read_bytes():
            fail("JSON report does not match the committed golden file")
        if first_markdown != expected_markdown.read_bytes():
            fail("Markdown report does not match the committed golden file")
        check_report_safety(first_json, "JSON report")
        if not first_markdown.endswith(b"\n"):
            fail("Markdown report does not end with one newline")
        check_text_safety(first_markdown.decode("utf-8"), "Markdown report")
        report_value = json.loads(first_json.decode("utf-8"))
        expect_forbidden_field_rejected(report_value, "pid", 1234)
        expect_forbidden_field_rejected(report_value, "uid", 1000)
        expect_forbidden_field_rejected(report_value, "vmRssBytes", 4096)
    with tempfile.TemporaryDirectory(prefix="native-mcp-demo-parent-") as parent:
        missing = Path(parent) / "created-by-demo"
        run_demo(demo, arguments.server.resolve(), fixture, missing)
        if (
            not (missing / "report.json").is_file()
            or not (missing / "report.md").is_file()
        ):
            fail("the demonstration did not create a missing output directory")
    run_real_agent_server_contract(arguments.server.resolve())
    run_output_flood_negative_test(demo, arguments.server.resolve(), fixture)
    print("Agent investigation demo and real agent/server contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
