"""Command-line entry point for the reproducible native demonstration."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .demo import SCENARIOS, DemoFailure, run_demo
from .errors import ProviderError


def main() -> int:
    parser = argparse.ArgumentParser(prog="native-mcp-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run synthetic evidence through the real C++ server")
    demo.add_argument("--server", type=Path, default=shutil.which("native-mcp-sandbox"))
    demo.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    demo.add_argument("--output", type=Path, default=Path("demo-output"))
    arguments = parser.parse_args()
    if arguments.server is None:
        parser.error("install native-mcp-sandbox on PATH or supply --server /path/to/binary")
    scenarios = SCENARIOS if arguments.scenario == "all" else (arguments.scenario,)
    try:
        for scenario in scenarios:
            destination = arguments.output / scenario
            report = run_demo(Path(arguments.server), scenario, destination)
            print(f"{scenario}: {report['result']} | {len(report['evidence'])} validated responses")
            for rejection in report["rejections"]:
                print(f"  {rejection['layer']}: {rejection['reason']}")
            print(f"  report: {destination / 'report.md'}")
    except (DemoFailure, ProviderError, OSError) as error:
        print(f"Demo failed: {error}", file=sys.stderr)
        print(
            "Requires strict Linux openat2 and pidfd support; no compatibility fallback is used.",
            file=sys.stderr,
        )
        return 1
    return 0
