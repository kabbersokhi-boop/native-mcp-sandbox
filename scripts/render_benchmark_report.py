#!/usr/bin/env python3
"""Render a bounded, non-canonical Markdown view from a benchmark JSON report."""
from __future__ import annotations
import argparse,json
from pathlib import Path
def main() -> int:
 p=argparse.ArgumentParser();p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path,default=Path("build/benchmark-report.md"));a=p.parse_args()
 data=json.loads(a.input.read_text(encoding="utf-8")); lines=["# Benchmark observation","","This is an environment-specific observation, not a deployment recommendation.","","| Case | Median ns/op | P95 ns/op | Samples |","| --- | ---: | ---: | ---: |"]
 for case in data["cases"]: lines.append(f"| {case['caseId']} | {case['median']:.2f} | {case['p95']:.2f} | {case['sampleCount']} |")
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text("\n".join(lines)+"\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())
