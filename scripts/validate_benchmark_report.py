#!/usr/bin/env python3
"""Offline validator for the repository benchmark report schema."""
from __future__ import annotations
import json
from pathlib import Path

SUPPORTED={"$schema","title","type","required","properties","items","minItems","maxItems","pattern","const","additionalProperties","minimum"}
def validate(value: object, schema_path: Path) -> None:
    schema=json.loads(schema_path.read_text(encoding="utf-8"))
    def walk(node: object, spec: dict[str,object], path: str) -> None:
        unknown=set(spec)-SUPPORTED
        if unknown: raise ValueError(f"unsupported schema keywords at {path}: {sorted(unknown)}")
        if "const" in spec and node != spec["const"]: raise ValueError(f"{path} does not match const")
        kind=spec.get("type")
        if kind=="object":
            if not isinstance(node,dict): raise ValueError(f"{path} is not an object")
            for key in spec.get("required",[]):
                if key not in node: raise ValueError(f"missing {path}.{key}")
            props=spec.get("properties",{})
            if spec.get("additionalProperties") is False and set(node)-set(props): raise ValueError(f"additional field at {path}")
            for key, child in node.items():
                if key in props: walk(child,props[key],f"{path}.{key}")
        elif kind=="array":
            if not isinstance(node,list): raise ValueError(f"{path} is not an array")
            if len(node)<spec.get("minItems",0) or len(node)>spec.get("maxItems",10**9): raise ValueError(f"array bounds at {path}")
            for index,child in enumerate(node): walk(child,spec["items"],f"{path}[{index}]")
        elif kind=="string":
            if not isinstance(node,str): raise ValueError(f"{path} is not a string")
            import re
            if "pattern" in spec and not re.search(spec["pattern"],node): raise ValueError(f"pattern mismatch at {path}")
        elif kind=="integer" and (not isinstance(node,int) or isinstance(node,bool) or node<spec.get("minimum",-10**18)): raise ValueError(f"invalid integer at {path}")
        elif kind=="number" and (not isinstance(node,(int,float)) or isinstance(node,bool) or node<spec.get("minimum",-10**18)): raise ValueError(f"invalid number at {path}")
    walk(value,schema,"$")
    if isinstance(value,dict) and isinstance(value.get("metadata"),dict):
        for key, record in value["metadata"].items():
            if key == "noiseControls": continue
            if not isinstance(record,dict) or record.get("available") not in (True,False): raise ValueError(f"metadata availability record invalid: {key}")
            if record["available"] and "value" not in record: raise ValueError(f"metadata value missing: {key}")
            if not record["available"] and not isinstance(record.get("reason"),str): raise ValueError(f"metadata reason missing: {key}")
    if isinstance(value,dict) and isinstance(value.get("cases"),list):
        for case in value["cases"]:
            allowed={"caseId","unit","inputBytes","operationCount","concurrency","timeoutMilliseconds","warmupIterations","measuredIterations","sampleCount","originalSampleCount","retainedSampleCount","excludedSampleCount","exclusionClasses","rawSamples","minimum","maximum","median","p95","mean","standardDeviation","validationInTimedRegion","noSamplesExcluded","optimizationSink"}
            if set(case)-allowed: raise ValueError("unexpected case field")
            if case.get("sampleCount") != len(case.get("rawSamples", [])): raise ValueError("sampleCount does not match rawSamples")
            if case.get("originalSampleCount") != case.get("retainedSampleCount", -1) + case.get("excludedSampleCount", -1): raise ValueError("sample accounting mismatch")
def main() -> int:
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument("report",type=Path); parser.add_argument("--schema",type=Path,default=Path("benchmarks/schema/benchmark-report.schema.json")); args=parser.parse_args()
    validate(json.loads(args.report.read_text(encoding="utf-8")),args.schema); print("benchmark schema validation passed"); return 0
if __name__=="__main__": raise SystemExit(main())
