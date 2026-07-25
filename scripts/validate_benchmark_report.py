#!/usr/bin/env python3
"""Small, strict offline validator for the repository benchmark schema."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

SUPPORTED = {
    "$schema",
    "title",
    "type",
    "required",
    "properties",
    "items",
    "minItems",
    "maxItems",
    "pattern",
    "const",
    "additionalProperties",
    "minimum",
}
TYPES = {"object", "array", "string", "integer", "number"}


def fail(message: str) -> None:
    raise ValueError(message)


def schema_walk(spec: Any, path: str) -> None:
    """Validate the schema itself so constructs are never silently ignored."""
    if not isinstance(spec, dict):
        fail(f"schema node at {path} is not an object")
    unknown = set(spec) - SUPPORTED
    if unknown:
        fail(f"unsupported schema keywords at {path}: {sorted(unknown)}")

    kind = spec.get("type")
    if kind is not None and (not isinstance(kind, str) or kind not in TYPES):
        fail(f"unsupported schema type at {path}: {kind!r}")
    required = spec.get("required", [])
    if not isinstance(required, list) or any(
        not isinstance(item, str) for item in required
    ):
        fail(f"invalid required list at {path}")
    properties = spec.get("properties", {})
    if not isinstance(properties, dict):
        fail(f"invalid properties at {path}")
    for key, child in properties.items():
        if not isinstance(key, str):
            fail(f"non-string property name at {path}")
        schema_walk(child, f"{path}.properties.{key}")
    if "items" in spec:
        schema_walk(spec["items"], f"{path}.items")
    additional = spec.get("additionalProperties", True)
    if not isinstance(additional, (bool, dict)):
        fail(f"invalid additionalProperties at {path}")
    if isinstance(additional, dict):
        schema_walk(additional, f"{path}.additionalProperties")
    for keyword in ("minItems", "maxItems"):
        if keyword in spec and (
            not isinstance(spec[keyword], int)
            or isinstance(spec[keyword], bool)
            or spec[keyword] < 0
        ):
            fail(f"invalid {keyword} at {path}")
    if spec.get("minItems", 0) > spec.get("maxItems", 2**63 - 1):
        fail(f"minItems exceeds maxItems at {path}")
    if "pattern" in spec:
        if not isinstance(spec["pattern"], str):
            fail(f"invalid pattern at {path}")
        try:
            re.compile(spec["pattern"])
        except re.error as error:
            fail(f"invalid pattern at {path}: {error}")
    if "minimum" in spec:
        minimum = spec["minimum"]
        if (
            not isinstance(minimum, (int, float))
            or isinstance(minimum, bool)
            or not math.isfinite(float(minimum))
        ):
            fail(f"invalid minimum at {path}")


def same_json_value(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def value_walk(node: Any, spec: dict[str, Any], path: str) -> None:
    if "const" in spec and not same_json_value(node, spec["const"]):
        fail(f"{path} does not match const")

    kind = spec.get("type")
    if kind == "object":
        if not isinstance(node, dict):
            fail(f"{path} is not an object")
        required = spec.get("required", [])
        for key in required:
            if key not in node:
                fail(f"missing {path}.{key}")
        properties = spec.get("properties", {})
        additional = spec.get("additionalProperties", True)
        for key, child in node.items():
            if key in properties:
                value_walk(child, properties[key], f"{path}.{key}")
            elif additional is False:
                fail(f"additional field at {path}: {key}")
            elif isinstance(additional, dict):
                value_walk(child, additional, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(node, list):
            fail(f"{path} is not an array")
        if len(node) < spec.get("minItems", 0) or len(node) > spec.get(
            "maxItems", 2**63 - 1
        ):
            fail(f"array bounds at {path}")
        if "items" in spec:
            for index, child in enumerate(node):
                value_walk(child, spec["items"], f"{path}[{index}]")
    elif kind == "string":
        if not isinstance(node, str):
            fail(f"{path} is not a string")
        if "pattern" in spec and re.search(spec["pattern"], node) is None:
            fail(f"pattern mismatch at {path}")
    elif kind == "integer":
        if not isinstance(node, int) or isinstance(node, bool):
            fail(f"{path} is not an integer")
    elif kind == "number":
        if not isinstance(node, (int, float)) or isinstance(node, bool):
            fail(f"{path} is not a number")
        if not math.isfinite(float(node)):
            fail(f"{path} is not finite")

    if kind in {"integer", "number"} and "minimum" in spec:
        if node < spec["minimum"]:
            fail(f"minimum violated at {path}")


def validate(value: object, schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"could not load schema: {error}")
    schema_walk(schema, "$schema")
    if not isinstance(schema, dict):
        fail("root schema is not an object")
    value_walk(value, schema, "$")

    if isinstance(value, dict) and isinstance(value.get("metadata"), dict):
        for key, record in value["metadata"].items():
            if key == "noiseControls":
                continue
            if not isinstance(record, dict) or type(record.get("available")) is not bool:
                fail(f"metadata availability record invalid: {key}")
            if record["available"] and "value" not in record:
                fail(f"metadata value missing: {key}")
            if not record["available"] and not isinstance(record.get("reason"), str):
                fail(f"metadata reason missing: {key}")

    if isinstance(value, dict) and isinstance(value.get("cases"), list):
        case_ids: set[str] = set()
        allowed = {
            "caseId", "unit", "inputBytes", "operationCount", "concurrency",
            "timeoutMilliseconds", "warmupIterations", "measuredIterations",
            "sampleCount", "originalSampleCount", "retainedSampleCount",
            "excludedSampleCount", "exclusionClasses", "rawSamples", "minimum",
            "maximum", "median", "p95", "mean", "standardDeviation",
            "validationInTimedRegion", "noSamplesExcluded", "optimizationSink",
        }
        for case in value["cases"]:
            if not isinstance(case, dict):
                fail("benchmark case is not an object")
            if set(case) - allowed:
                fail("unexpected case field")
            case_id = case.get("caseId")
            if isinstance(case_id, str):
                case_ids.add(case_id)
            samples = case.get("rawSamples", [])
            if case.get("sampleCount") != len(samples):
                fail("sampleCount does not match rawSamples")
            if case.get("originalSampleCount") != case.get("retainedSampleCount", -1) + case.get("excludedSampleCount", -1):
                fail("sample accounting mismatch")

        groups = value.get("comparisonGroups", [])
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, dict) or len(group.get("cases", [])) != 2:
                    fail("invalid comparison group")
                if any(case_id not in case_ids for case_id in group["cases"]):
                    fail("comparison group references an unknown case")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("benchmarks/schema/benchmark-report.schema.json"),
    )
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        validate(report, args.schema)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"benchmark schema validation failed: {error}")
    print("benchmark schema validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
