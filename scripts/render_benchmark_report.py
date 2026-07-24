#!/usr/bin/env python3
"""Render a bounded, non-canonical Markdown view from a benchmark JSON report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

UNIT_LABELS = {
    "nanoseconds_per_operation": "ns/operation",
    "nanoseconds_per_scenario": "ns/scenario",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/benchmark-report.md"),
    )
    arguments = parser.parse_args()
    data = json.loads(arguments.input.read_text(encoding="utf-8"))
    lines = [
        "# Benchmark observation",
        "",
        "This is an environment-specific observation, not a deployment recommendation.",
        "",
        "| Case | Unit | Median | P95 | Samples |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for case in data["cases"]:
        unit = case["unit"]
        if unit not in UNIT_LABELS:
            raise ValueError(f"unsupported benchmark unit: {unit}")
        lines.append(
            f"| {case['caseId']} | {UNIT_LABELS[unit]} | "
            f"{case['median']:.2f} | {case['p95']:.2f} | "
            f"{case['sampleCount']} |"
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
