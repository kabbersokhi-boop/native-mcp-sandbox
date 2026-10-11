#!/usr/bin/env python3
"""Export only synthetic, reviewable artifacts to the static public site."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

from evaluate_boundaries import evaluate
from run_runtime_study import source_metadata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from native_mcp_agent.demo import SCENARIOS, run_demo


def build(server: Path, study: Path, destination: Path) -> None:
    observed = json.loads((study / "study.json").read_text())
    if observed["serverSha256"] != hashlib.sha256(server.read_bytes()).hexdigest():
        raise RuntimeError("study was measured with a different native executable")
    with tempfile.TemporaryDirectory(prefix="nms-public-") as directory:
        scratch = Path(directory)
        staged = scratch / "public"
        staged.mkdir()
        for scenario in SCENARIOS:
            run_demo(server, scenario, scratch / scenario)
            target = staged / scenario
            target.mkdir(exist_ok=True)
            for name in ("report.json", "report.md", "transcript.json"):
                shutil.copyfile(scratch / scenario / name, target / name)
        evaluation = evaluate(server.resolve(), scratch / "evaluation", extended=True)
        if not evaluation["passed"]:
            failure = ROOT / "build/public-evidence-failure"
            shutil.copytree(scratch / "evaluation", failure, dirs_exist_ok=True)
            raise RuntimeError(f"boundary evaluation failed; evidence retained at {failure}")
        for name in ("evaluation.json", "evaluation.md"):
            shutil.copyfile(scratch / "evaluation" / name, staged / name)
        shutil.copytree(scratch / "evaluation/suites", staged / "suites")
        for name in ("study.json", "study.md", "latency.svg"):
            shutil.copyfile(study / name, staged / name)
        shutil.copytree(staged, destination, dirs_exist_ok=True)
    assets = {str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(destination.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    manifest = {"schemaVersion": 1, "publication": "source v0.13.0 evidence; not a tagged release",
                "source": source_metadata(), "serverSha256": observed["serverSha256"],
                "artifacts": assets,
                "limits": ["Recorded synthetic runs; no browser-hosted Linux sandbox.",
                           "Report hashes detect changes; they do not authenticate an attacker-rewritten manifest.",
                           "Study source metadata identifies its measurement source separately from this export."]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Exported {len(assets)} synthetic evidence artifacts to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "site/data")
    arguments = parser.parse_args()
    build(arguments.server, arguments.study, arguments.output)
