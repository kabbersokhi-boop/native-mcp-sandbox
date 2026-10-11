#!/usr/bin/env python3
"""Retain raw native measurements and the exact measured source fingerprints."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import platform
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from evaluate_boundaries import call, lifecycle, wire
from stdio_harness import exchange

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from native_mcp_agent.demo import write_elf


def source_metadata() -> dict:
    files = {}
    for folder in ("src", "include", "benchmarks", "agent/native_mcp_agent", "scripts"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and path.suffix in {".cpp", ".hpp", ".py"}:
                files[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("CMakeLists.txt", "CMakePresets.json", "agent/pyproject.toml"):
        files[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"baseCommit": base, "workingTreeModified": dirty,
            "sourceFingerprint": digest, "fileSha256": files}


def summary(samples: list[int]) -> dict:
    result = {"unit": "nanoseconds_per_scenario", "rawSamples": samples,
              "sampleCount": len(samples), "median": statistics.median(samples),
              "minimum": min(samples), "maximum": max(samples)}
    if len(samples) >= 100:
        result["p95"] = sorted(samples)[(95 * len(samples) + 99) // 100 - 1]
    return result


def checked_exchange(command: list[str], payload: bytes, identifiers: set[int]) -> int:
    run = exchange(command, payload, timeout=10)
    if run.status or run.stderr:
        raise RuntimeError(f"native scenario failed: status={run.status}, stderr={run.stderr[:500]!r}")
    values = [json.loads(line) for line in run.stdout.splitlines()]
    if len(values) != len(identifiers) or {item.get("id") for item in values} != identifiers:
        raise RuntimeError("native scenario returned an unexpected response set")
    for item in values:
        if "error" in item or item.get("result", {}).get("isError"):
            raise RuntimeError("native scenario returned an error")
    return run.elapsed_ns


def render(report: dict, output: Path) -> None:
    lines = ["# Native runtime study", "", f"Mode: {report['mode']}. Raw samples are in study.json.", "",
             "Component measurements include strict file opens and analyzers, but exclude MCP serialization.",
             "Stdio scenarios include process creation, protocol I/O and shutdown.", "",
             "| Fixture | Size | No-match scan median | Tail median | Harness peak RSS |",
             "| --- | ---: | ---: | ---: | ---: |"]
    chart_rows = []
    for result in report["components"]:
        cases = {case["case"]: case for case in result["cases"]}
        scan = cases["logs.search.no-match"]["median"] / 1e6
        tail = cases["logs.tail"]["median"] / 1e6
        lines.append(f"| {result['log']} | {result['inputBytes']} B | {scan:.3f} ms | {tail:.3f} ms | "
                     f"{result['peakRssBytes'] / 1048576:.2f} MiB |")
        chart_rows.append((result["log"], scan, tail))
    lines.extend(["", "## Stdio scenarios", ""])
    for name, result in report["stdio"].items():
        lines.append(f"- {name}: median {result['median'] / 1e6:.3f} ms "
                     f"({result['sampleCount']} retained samples).")
    lines.extend(["", "## Interpretation", "", *["- " + item for item in report["limitations"]], ""])
    (output / "study.md").write_text("\n".join(lines))
    maximum = max(max(scan, tail) for _, scan, tail in chart_rows)
    height = 110 + len(chart_rows) * 80
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {height}" role="img" '
           'aria-labelledby="title desc">',
           '<title id="title">Native scan and tail latency</title>',
           '<desc id="desc">Median component latency in milliseconds. Raw data is in study.json.</desc>',
           f'<rect width="900" height="{height}" fill="#101827"/>',
           '<g fill="#edf2f7" font-family="sans-serif" font-size="16">',
           '<text x="28" y="32">Native component latency · median milliseconds</text>',
           '<text x="28" y="58">Blue: no-match scan   Mint: tail · same strict file policy</text>']
    for index, (name, scan, tail) in enumerate(chart_rows):
        baseline = 100 + index * 80
        svg.append(f'<text x="28" y="{baseline + 12}">{html.escape(name)}</text>')
        for offset, value, color in ((0, scan, "#7cb8ff"), (25, tail, "#68e0b5")):
            width = max(1, value / maximum * 430)
            svg.append(f'<rect x="290" y="{baseline + offset}" width="{width:.1f}" height="18" fill="{color}"/>')
            svg.append(f'<text x="{300 + width:.1f}" y="{baseline + offset + 15}">{value:.3f}</text>')
    svg.append("</g></svg>\n")
    (output / "latency.svg").write_text("\n".join(svg))


def run_study(server: Path, benchmark: Path, mode: str, output: Path) -> dict:
    samples = 5 if mode == "smoke" else 100
    metadata = source_metadata()
    components = []
    fixture_hashes = {}
    with tempfile.TemporaryDirectory(prefix="nms-study-") as directory:
        fixtures = Path(directory)
        write_elf(fixtures / "sample.elf", 62)
        sizes = (16 * 1024, 256 * 1024, 4 * 1024 * 1024, 16 * 1024 * 1024)
        shapes = [(f"dense-{size}.log", (b"needle " + b"x" * 56 + b"\n") * (size // 64)) for size in sizes]
        shapes.append(("long-line-4194304.log", b"needle " + b"x" * (4 * 1024 * 1024 - 8) + b"\n"))
        shapes.append(("sparse-4194304.log", b"needle\n" + b"other line\n" * 381299))
        for name, content in shapes:
            (fixtures / name).write_bytes(content)
            fixture_hashes[name] = hashlib.sha256(content).hexdigest()
            observation = exchange([str(benchmark.resolve()), str(fixtures), name, str(samples)], b"", timeout=60)
            if observation.status or observation.stderr:
                raise RuntimeError(f"native study failed: {observation.stderr[:1000]!r}")
            result = json.loads(observation.stdout)
            if result["samples"] != samples or result["inputBytes"] != len(content):
                raise RuntimeError("native sample metadata mismatch")
            if result["threadsAfterJoin"] != 1:
                raise RuntimeError("native worker thread leaked after join")
            for case in result["cases"]:
                if len(case["rawSamples"]) != samples or any(value < 0 for value in case["rawSamples"]):
                    raise RuntimeError("invalid raw native measurements")
            components.append(result)
        policy = fixtures / "policy.json"
        policy.write_bytes(wire({"version": 2, "roots": [{"name": "evidence", "path": str(fixtures),
            "maxFileBytes": 16 * 1024 * 1024}], "processes": [{"name": "server", "pid": "self"}]}))
        configured = [str(server.resolve()), "--policy-config", str(policy)]
        investigation = lifecycle()
        tools = [("logs.search", {"root": "evidence", "path": shapes[0][0], "query": "needle"}),
                 ("logs.tail", {"root": "evidence", "path": shapes[0][0], "maxLines": 3}),
                 ("elf.inspect", {"root": "evidence", "path": "sample.elf"}),
                 ("proc.memory", {"process": "server"})]
        for request_id, (name, arguments) in enumerate(tools, 2):
            message = json.loads(call(name, arguments))
            message["id"] = request_id
            investigation += wire(message)
        concurrent = lifecycle()
        for request_id in range(2, 18):
            message = json.loads(call("logs.search", {"root": "evidence", "path": shapes[2][0], "query": "ABSENT_SENTINEL"}))
            message["id"] = request_id
            concurrent += wire(message)
        scenarios = {
            "cold-start-initialize": ([str(server.resolve())], lifecycle(), {1}),
            "four-tool-investigation": (configured, investigation, set(range(1, 6))),
            "sixteen-concurrent-scans": (configured, concurrent, set(range(1, 18))),
        }
        stdio = {}
        for name, (command, payload, expected) in scenarios.items():
            checked_exchange(command, payload, expected)
            values = [checked_exchange(command, payload, expected) for _ in range(samples)]
            stdio[name] = summary(values)
            stdio[name]["warmupIterations"] = 1
            if name == "sixteen-concurrent-scans":
                stdio[name]["medianCallsPerSecondIncludingStartup"] = 16 * 1e9 / statistics.median(values)
    cpu = next((line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), "unavailable")
    cache_path = benchmark.parent / "CMakeCache.txt"
    build_settings = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            if line.startswith(("CMAKE_BUILD_TYPE:", "CMAKE_CXX_COMPILER:", "CMAKE_CXX_FLAGS:",
                                "CMAKE_CXX_FLAGS_RELEASE:", "NMS_ENABLE_SANITIZERS:",
                                "NMS_ENABLE_THREAD_SANITIZER:", "NMS_WARNINGS_AS_ERRORS:")):
                key, _, value = line.partition("=")
                build_settings[key] = value
    report = {"schemaVersion": 1, "mode": mode, "source": metadata,
              "environment": {"kernel": platform.release(), "machine": platform.machine(), "cpu": cpu,
                              "buildSettings": build_settings, "python": platform.python_version()},
              "serverSha256": hashlib.sha256(server.read_bytes()).hexdigest(),
              "benchmarkSha256": hashlib.sha256(benchmark.read_bytes()).hexdigest(),
              "fixtureSha256": fixture_hashes, "components": components, "stdio": stdio,
              "limitations": [
                  "Measurements describe this machine and these binaries, not a universal language ranking.",
                  "Component peak RSS is the native measurement process, including result storage and scheduler probe; it is not server-only RSS.",
                  "Descriptor counts include the descriptor used to enumerate /proc/self/fd. Before/after counts use the same method.",
                  "Cancellation timing uses cooperative synthetic work. It does not bound arbitrary filesystem system calls.",
                  "All valid samples are retained in execution order; no outlier filtering. Fixtures run in the listed order with warm caches.",
                  "DOM-only is an unsafe measurement reference, never a deployable server option.",
                  "No p99 claim. p95 appears only with at least 100 samples and is descriptive, without a confidence claim.",
              ]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "study.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    render(report, output)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "study"), default="smoke")
    parser.add_argument("--output", type=Path, default=Path("build/runtime-study"))
    arguments = parser.parse_args()
    report = run_study(arguments.server, arguments.benchmark, arguments.mode, arguments.output)
    print(f"{report['mode']}: {len(report['components'])} fixture processes, {len(report['stdio'])} stdio scenarios")
    print(arguments.output / "study.md")
