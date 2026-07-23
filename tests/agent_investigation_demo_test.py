#!/usr/bin/env python3
"""Run the Phase 8 demonstration twice and compare canonical reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


EXPECTED_CONCLUSION = "healthy_final_state_confirmed"


def fail(message: str) -> None:
    raise AssertionError(message)


def run_demo(demo: Path, server: Path, fixture: Path, output_dir: Path) -> None:
    try:
        result = subprocess.run(
            [sys.executable, str(demo), "--server", str(server), "--fixture", str(fixture), "--output-dir", str(output_dir)],
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


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    source_dir = Path(__file__).resolve().parents[1]
    demo = source_dir / "scripts" / "run_agent_investigation_demo.py"
    fixture = source_dir / "demo" / "investigation" / "application.log"
    expected_json = source_dir / "demo" / "investigation" / "expected-report.json"
    expected_markdown = source_dir / "demo" / "investigation" / "expected-report.md"
    with tempfile.TemporaryDirectory(prefix="native-mcp-demo-test-") as first, tempfile.TemporaryDirectory(prefix="native-mcp-demo-test-") as second:
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
    print("Agent investigation demo is deterministic and matches its golden reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
