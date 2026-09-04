#!/usr/bin/env python3
"""Validate deterministic structural benchmark-report invariants."""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_benchmark_report import validate


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: benchmark_invariant_tests.py REPORT")
    raw = Path(sys.argv[1]).read_bytes()
    fail("missing final newline") if not raw.endswith(b"\n") else None
    report = json.loads(raw)
    validate(
        report,
        Path(__file__).resolve().parents[1]
        / "benchmarks/schema/benchmark-report.schema.json",
    )
    fail("incomplete report") if report.get("complete") is not True else None
    fail("wrong schema") if report.get("schemaVersion") != "1.0.0" else None
    cases = report.get("cases")
    fail("cases missing") if not isinstance(cases, list) or not cases else None
    for case in cases:
        samples = case["rawSamples"]
        fail("unbounded samples") if not 1 <= len(samples) <= 15 else None
        fail("sample count mismatch") if case["sampleCount"] != len(samples) else None
        fail("automatic exclusions") if case["excludedSampleCount"] != 0 else None
        fail("invalid unit") if case["unit"] not in {
            "nanoseconds_per_operation",
            "nanoseconds_per_scenario",
        } else None
        fail("missing no-exclusion declaration") if case.get(
            "noSamplesExcluded"
        ) is not True else None
    print("benchmark report structural invariants passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
