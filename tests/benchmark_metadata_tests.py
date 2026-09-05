#!/usr/bin/env python3
"""Deterministic tests for benchmark host metadata decoding."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_benchmarks import decode_turbo_probe, select_turbo_probe


def expect(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    expect(
        decode_turbo_probe("intel_pstate/no_turbo", "0"),
        {"available": True, "value": "enabled"},
        "Intel no_turbo=0",
    )
    expect(
        decode_turbo_probe("intel_pstate/no_turbo", "1"),
        {"available": True, "value": "disabled"},
        "Intel no_turbo=1",
    )
    expect(
        decode_turbo_probe("cpufreq/boost", "0"),
        {"available": True, "value": "disabled"},
        "generic boost=0",
    )
    expect(
        decode_turbo_probe("cpufreq/boost", "1"),
        {"available": True, "value": "enabled"},
        "generic boost=1",
    )
    expect(
        select_turbo_probe(
            {"available": False, "reason": "missing"},
            {"available": True, "value": "1"},
        ),
        {"available": True, "value": "enabled"},
        "fallback selection",
    )
    missing = select_turbo_probe(
        {"available": False, "reason": "missing primary"},
        {"available": False, "reason": "missing fallback"},
    )
    expect(missing["available"], False, "missing probes availability")
    expect(
        missing["reason"],
        "Intel pstate no_turbo and generic cpufreq boost probes were not available",
        "missing probes reason",
    )
    for source in ("intel_pstate/no_turbo", "cpufreq/boost"):
        invalid = decode_turbo_probe(source, "2")
        expect(invalid["available"], False, f"unexpected {source} availability")
        if "unexpected value" not in str(invalid["reason"]):
            raise AssertionError(f"unexpected {source} value lacked a clear reason")
    print("benchmark turbo metadata decoding tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
