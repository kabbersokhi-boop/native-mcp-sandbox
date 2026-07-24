#!/usr/bin/env python3
"""Deterministic bounds and semantic rejection tests for the benchmark driver."""
from __future__ import annotations
import json, os, stat, sys, tempfile, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_benchmarks
from validate_benchmark_report import validate

def fake(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8"); path.chmod(stat.S_IRWXU)
def rejects(command: list[str], data: bytes = b"") -> None:
    try: run_benchmarks.bounded_run(command, data)
    except Exception: return
    raise AssertionError("bounded subprocess unexpectedly accepted")
def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nms-benchmark-failure-") as directory:
        root=Path(directory); timeout=root/"timeout"; flood=root/"flood"; err=root/"err"; nonzero=root/"nonzero"; malformed=root/"malformed"
        fake(timeout,"import time; time.sleep(20)"); fake(flood,"import sys; sys.stdout.write('x'*300000)"); fake(err,"import sys; sys.stderr.write('unexpected')"); fake(nonzero,"raise SystemExit(3)"); fake(malformed,"print('not-json')")
        rejects([str(timeout)]); rejects([str(flood)]); rejects([str(err)]); rejects([str(nonzero)])
        try: run_benchmarks.validate_responses(b"not-json\n", False)
        except Exception: pass
        else: raise AssertionError("malformed JSON output accepted")
        stale=root/"stale.json"; stale.write_text('{"complete":true}',encoding="utf-8")
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"scripts/run_benchmarks.py"),"--benchmark",str(timeout),"--server",str(timeout),"--fixtures",str(Path(__file__).resolve().parents[1]/"benchmarks/fixtures"),"--output",str(stale)],capture_output=True,timeout=15)
        if result.returncode==0 or stale.exists(): raise AssertionError("failed campaign left a complete report")
        valid_unconfigured = b'{"id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{}}}\n{"id":2,"result":{"tools":[]}}\n'
        for bad in (valid_unconfigured.replace(b'"result"', b'"error"', 1), valid_unconfigured + valid_unconfigured.splitlines()[0] + b'\n', valid_unconfigured.splitlines()[0] + b'\n', valid_unconfigured.replace(b'"tools":[]', b'"tools":"bad"')):
            try: run_benchmarks.validate_responses(bad, False)
            except Exception: pass
            else: raise AssertionError("invalid response semantics accepted")
        metadata={key:{"available":True,"value":"x"} for key in ("repositoryCommit","dirtyWorktree","benchmarkExecutableSha256","serverExecutableSha256","schemaVersion","fixtureSetVersion","harnessVersion","commandLineArguments")}
        sample={"caseId":"component.x","unit":"nanoseconds_per_operation","sampleCount":1,"originalSampleCount":1,"retainedSampleCount":1,"excludedSampleCount":0,"noSamplesExcluded":True,"rawSamples":[1.0],"median":1.0,"minimum":1.0,"maximum":1.0,"mean":1.0,"standardDeviation":0.0,"p95":1.0}
        good={"schemaVersion":"1.0.0","fixtureSetVersion":"1","harnessVersion":"1","framework":{"name":"x","version":"1"},"outlierPolicy":"x","metadata":metadata,"cases":[sample],"comparisonGroups":[],"complete":True}
        mutations=[{"complete":False},{"cases":[dict(sample,caseId="bad")]},{"cases":[dict(sample,unit="bogus")]},{"cases":[dict(sample,rawSamples=[1.0]*16)]},{"cases":[dict(sample,sampleCount=2)]},{"cases":[dict(sample,excludedSampleCount=1)]},{"cases":[dict(sample,unexpected=True)]},{"metadata":dict(metadata,broken="empty")},{"missing":"schemaVersion"}]
        for mutation in mutations:
            candidate=json.loads(json.dumps(good)); candidate.pop(mutation.get("missing","__none__"),None); candidate.update({key:value for key,value in mutation.items() if key!="missing"})
            try: validate(candidate,Path(__file__).resolve().parents[1] / "benchmarks/schema/benchmark-report.schema.json")
            except Exception: continue
            raise AssertionError(f"invalid schema report accepted: {mutation}")
        try:
            invalid_complete=dict(good, complete=False)
            validate(invalid_complete,Path(__file__).resolve().parents[1] / "benchmarks/schema/benchmark-report.schema.json")
        except Exception: pass
        else: raise AssertionError("invalid complete flag accepted")
    print("benchmark failure bounds and semantic negatives passed"); return 0
if __name__=="__main__": raise SystemExit(main())
