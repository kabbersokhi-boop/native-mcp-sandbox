#!/usr/bin/env python3
"""Run bounded Phase 9 benchmark smoke campaigns and write canonical JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import selectors
import shlex
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean, median, pstdev

SCHEMA_VERSION = "1.0.0"
FIXTURE_SET_VERSION = "1.0.0"
HARNESS_VERSION = "1.0.0"
OUTPUT_LIMIT = 256 * 1024
STDERR_LIMIT = 64 * 1024
PROCESS_TIMEOUT = 10.0
MAX_SAMPLES = 15


def decode_turbo_probe(source: str, raw_value: str) -> dict[str, object]:
    """Decode one read-only Linux turbo probe using that source's polarity."""
    mappings = {
        "intel_pstate/no_turbo": {"0": "enabled", "1": "disabled"},
        "cpufreq/boost": {"0": "disabled", "1": "enabled"},
    }
    mapping = mappings.get(source)
    if mapping is None:
        return {
            "available": False,
            "reason": f"unsupported turbo probe source: {source}",
        }
    normalized = raw_value.strip()
    state = mapping.get(normalized)
    if state is None:
        return {
            "available": False,
            "reason": (
                f"{source} returned unexpected value {normalized!r}; "
                "expected 0 or 1"
            ),
        }
    return {"available": True, "value": state}


def select_turbo_probe(
    primary: dict[str, object], fallback: dict[str, object]
) -> dict[str, object]:
    """Prefer Intel pstate, then generic boost, preserving unavailable reasons."""
    if primary.get("available") is True:
        return decode_turbo_probe("intel_pstate/no_turbo", str(primary["value"]))
    if fallback.get("available") is True:
        return decode_turbo_probe("cpufreq/boost", str(fallback["value"]))
    return {
        "available": False,
        "reason": (
            "Intel pstate no_turbo and generic cpufreq boost probes were "
            "not available"
        ),
    }


def fail(message: str) -> None:
    raise RuntimeError(message)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def bounded_run(command: list[str], data: bytes, strict_stderr: bool = True) -> bytes:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(data)
    process.stdin.close()
    selector = selectors.DefaultSelector()
    buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
    for stream in buffers:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + PROCESS_TIMEOUT
    try:
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                fail("subprocess lifetime limit exceeded")
            for key, _ in selector.select(remaining):
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 8192)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                buffers[stream].extend(chunk)
                limit = OUTPUT_LIMIT if stream is process.stdout else STDERR_LIMIT
                if len(buffers[stream]) > limit:
                    fail("subprocess output byte limit exceeded")
        if process.wait(timeout=0.1) != 0:
            fail("benchmark subprocess failed")
        if strict_stderr and buffers[process.stderr]:
            fail("strict benchmark subprocess wrote standard error")
        return bytes(buffers[process.stdout])
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        selector.close()


def percentile(values: list[float], rank: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * rank + 0.999999))
    return ordered[index]


def summary(
    case_id: str,
    samples: list[float],
    input_bytes: int,
    operations: int,
    unit: str = "nanoseconds_per_operation",
    concurrency: int = 1,
    validation_in_timed_region: bool = True,
) -> dict[str, object]:
    if not samples or len(samples) > MAX_SAMPLES:
        fail("invalid sample count")
    ordered = sorted(samples)
    return {
        "caseId": case_id,
        "unit": unit,
        "inputBytes": input_bytes,
        "operationCount": operations,
        "concurrency": concurrency,
        "timeoutMilliseconds": int(PROCESS_TIMEOUT * 1000),
        "warmupIterations": 1,
        "measuredIterations": operations,
        "sampleCount": len(samples),
        "originalSampleCount": len(samples),
        "retainedSampleCount": len(samples),
        "excludedSampleCount": 0,
        "exclusionClasses": [],
        "noSamplesExcluded": True,
        "rawSamples": samples,
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "median": median(samples),
        "p95": percentile(samples, 0.95),
        "mean": mean(samples),
        "standardDeviation": pstdev(samples),
        "validationInTimedRegion": validation_in_timed_region,
    }


def requests(configured: bool, root: Path, policy_directory: Path) -> tuple[list[str], bytes]:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "phase-9", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    command: list[str] = []
    if configured:
        policy_directory.mkdir(parents=True, exist_ok=True)
        policy = policy_directory / "benchmark-policy.json"
        policy.write_text(
            canonical(
                {
                    "version": 2,
                    "roots": [
                        {
                            "name": "fixtures",
                            "path": str(root.resolve()),
                            "maxFileBytes": 65536,
                        }
                    ],
                    "processes": [{"name": "server", "pid": "self"}],
                }
            ),
            encoding="utf-8",
        )
        command = ["--policy-config", str(policy)]
        calls = [
            (
                "logs.search",
                {
                    "root": "fixtures",
                    "path": "log.txt",
                    "query": "needle",
                    "caseSensitive": True,
                    "maxMatches": 10,
                },
            ),
            ("logs.tail", {"root": "fixtures", "path": "log.txt", "maxLines": 2}),
            ("elf.inspect", {"root": "fixtures", "path": "minimal.elf"}),
            ("proc.memory", {"process": "server"}),
        ]
        for index, (name, arguments) in enumerate(calls, 10):
            messages.append(
                {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
            )
    payload = "".join(canonical(message) for message in messages).encode()
    return command, payload


def validate_responses(output: bytes, configured: bool) -> None:
    try:
        responses = [json.loads(line) for line in output.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"malformed JSON-RPC output: {error}")
    expected = ({1, 2} | set(range(10, 14))) if configured else {1, 2}
    found: list[int] = []
    for response in responses:
        if not isinstance(response, dict) or "id" not in response or response["id"] in found:
            fail("missing or duplicate response ID")
        if (
            response["id"] not in expected
            or "error" in response
            or not isinstance(response.get("result"), dict)
        ):
            fail("unexpected ID, JSON-RPC error, or malformed result")
        found.append(response["id"])
    if set(found) != expected:
        fail("incomplete response set")

    initialize = next(response for response in responses if response["id"] == 1)
    listing = next(response for response in responses if response["id"] == 2)
    if initialize["result"].get("protocolVersion") != "2025-11-25" or not isinstance(
        initialize["result"].get("capabilities"), dict
    ):
        fail("invalid initialize result")
    tools = listing["result"].get("tools")
    if not isinstance(tools, list) or (not configured and tools != []):
        fail("unexpected unconfigured tools/list surface")
    if configured and {tool.get("name") for tool in tools} != {
        "logs.search",
        "logs.tail",
        "elf.inspect",
        "proc.memory",
    }:
        fail("unexpected configured tools/list surface")

    if configured:
        results = {
            response["id"]: response["result"]
            for response in responses
            if response["id"] >= 10
        }
        for identifier in range(10, 14):
            content = results[identifier].get("content")
            structured = results[identifier].get("structuredContent")
            if (
                not isinstance(content, list)
                or len(content) != 1
                or not isinstance(structured, dict)
                or not isinstance(content[0], dict)
                or content[0].get("type") != "text"
            ):
                fail("invalid MCP tool result")
            try:
                text_content = json.loads(content[0]["text"])
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                fail(f"invalid tool text result: {error}")
            if text_content != structured:
                fail("tool text and structured result differ")

        search = results[10]["structuredContent"]
        tail = results[11]["structuredContent"]
        elf = results[12]["structuredContent"]
        if len(search.get("matches", [])) != 3 or len(tail.get("lines", [])) != 2:
            fail("fixture log conclusion mismatch")
        if elf.get("class") != "ELF64" or elf.get("machine") != "x86_64":
            fail("fixture ELF conclusion mismatch")
        process = results[13]["structuredContent"]
        if process.get("process") != "server" or process.get("pidfdPinned") is not True:
            fail("invalid configured process alias result")


def e2e_case(
    case_id: str,
    server: Path,
    configured: bool,
    fixtures: Path,
    policy_directory: Path,
) -> dict[str, object]:
    command, payload = requests(configured, fixtures, policy_directory)
    warmup = bounded_run([str(server), *command], payload)
    validate_responses(warmup, configured)
    samples: list[float] = []
    for _ in range(5):
        started = time.monotonic_ns()
        output = bounded_run([str(server), *command], payload)
        elapsed = float(time.monotonic_ns() - started)
        validate_responses(output, configured)
        samples.append(elapsed)
    return summary(
        case_id,
        samples,
        len(payload),
        1,
        "nanoseconds_per_scenario",
        4 if configured else 1,
        validation_in_timed_region=False,
    )


def metadata(benchmark: Path, server: Path, argv: list[str]) -> dict[str, object]:
    def value(item: object) -> dict[str, object]:
        return {"available": True, "value": item}

    def unavailable(reason: str) -> dict[str, object]:
        return {"available": False, "reason": reason}

    def environment(name: str) -> dict[str, object]:
        item = os.environ.get(name)
        return value(item) if item else unavailable(f"{name} was not provided")

    def probe(command: list[str]) -> dict[str, object]:
        try:
            output = subprocess.check_output(
                command,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            return value(output) if output else unavailable("probe returned no value")
        except (OSError, subprocess.CalledProcessError):
            return unavailable("probe failed")

    def read_probe(path: Path, missing_reason: str) -> dict[str, object]:
        try:
            output = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return unavailable(missing_reason)
        return value(output) if output else unavailable("probe returned no value")

    def cache_entries(build_directory: Path) -> dict[str, str]:
        cache = build_directory / "CMakeCache.txt"
        try:
            lines = cache.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return {}
        entries: dict[str, str] = {}
        for line in lines:
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            if ":" not in line or "=" not in line:
                continue
            key_type, item = line.split("=", 1)
            key, _ = key_type.split(":", 1)
            entries[key] = item
        return entries

    def normalize_token(token: str, build_directory: Path) -> str:
        source_directory = Path(__file__).resolve().parents[1]
        return token.replace(str(build_directory), "<build>").replace(
            str(source_directory), "<source>"
        )

    def build_evidence() -> dict[str, dict[str, object]]:
        build_directory = benchmark.resolve().parent
        cache = cache_entries(build_directory)
        if not cache:
            return {
                "compilerName": unavailable("CMakeCache.txt was not available"),
                "compilerVersion": unavailable("CMakeCache.txt was not available"),
                "buildType": unavailable("CMakeCache.txt was not available"),
                "cmakeGenerator": unavailable("CMakeCache.txt was not available"),
                "cmakeCacheOptions": unavailable("CMakeCache.txt was not available"),
                "compileFlags": unavailable("compile_commands.json was not available"),
                "linkFlags": unavailable("generated link commands were not available"),
                "linkCommands": unavailable("generated link commands were not available"),
            }

        compiler = cache.get("CMAKE_CXX_COMPILER")
        compiler_version = cache.get("CMAKE_CXX_COMPILER_VERSION")
        if compiler:
            try:
                compiler_version = subprocess.check_output(
                    [compiler, "--version"],
                    text=True,
                    stderr=subprocess.STDOUT,
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                pass

        relevant = {
            key: normalize_token(item, build_directory)
            for key, item in cache.items()
            if key.startswith("NMS_")
            or key
            in {
                "BUILD_TESTING",
                "CMAKE_BUILD_TYPE",
                "CMAKE_CXX_FLAGS",
                "CMAKE_CXX_FLAGS_DEBUG",
                "CMAKE_CXX_FLAGS_RELEASE",
                "CMAKE_CXX_FLAGS_RELWITHDEBINFO",
                "CMAKE_EXPORT_COMPILE_COMMANDS",
                "CMAKE_CXX_STANDARD",
            }
        }

        compile_commands = build_directory / "compile_commands.json"
        compile_flags: set[str] = set()
        try:
            commands = json.loads(compile_commands.read_text(encoding="utf-8"))
            for entry in commands:
                arguments = entry.get("arguments")
                if arguments is None:
                    arguments = shlex.split(entry["command"])
                for argument in arguments[1:]:
                    normalized = normalize_token(str(argument), build_directory)
                    if normalized.startswith("-") and normalized not in {"-c", "-o"}:
                        compile_flags.add(normalized)
        except (OSError, KeyError, TypeError, ValueError):
            compile_flags = set()

        link_commands: list[str] = []
        try:
            result = subprocess.run(
                ["ninja", "-C", str(build_directory), "-t", "commands", "native_mcp_bench", "native-mcp-sandbox"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if " -o native_mcp_bench" in line or " -o native-mcp-sandbox" in line:
                    if " -c " not in line:
                        link_commands.append(normalize_token(line, build_directory))
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            link_commands = []

        compiler_name = Path(compiler).name if compiler else None
        link_flags: set[str] = set()
        for command in link_commands:
            for argument in shlex.split(command):
                if argument.startswith("-") and argument not in {"-o"}:
                    link_flags.add(argument)

        return {
            "compilerName": value(compiler_name)
            if compiler_name
            else unavailable("compiler identity was not in CMakeCache.txt"),
            "compilerVersion": value(compiler_version)
            if compiler_version
            else unavailable("compiler version was not in CMakeCache.txt"),
            "buildType": value(cache.get("CMAKE_BUILD_TYPE"))
            if cache.get("CMAKE_BUILD_TYPE")
            else unavailable("build type was not in CMakeCache.txt"),
            "cmakeGenerator": value(cache.get("CMAKE_GENERATOR"))
            if cache.get("CMAKE_GENERATOR")
            else unavailable("generator was not in CMakeCache.txt"),
            "cmakeCacheOptions": value(relevant),
            "compileFlags": value(sorted(compile_flags))
            if compile_flags
            else unavailable("compile_commands.json contained no compile flags"),
            "linkFlags": value(sorted(link_flags))
            if link_flags
            else unavailable("Ninja did not expose bounded link flags"),
            "linkCommands": value(link_commands)
            if link_commands
            else unavailable("Ninja did not expose bounded link commands"),
        }

    cpu_model = unavailable("CPU model was not exposed")
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                cpu_model = value(line.split(":", 1)[1].strip())
                break

    try:
        dirty = value(
            bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"],
                    text=True,
                ).strip()
            )
        )
    except (OSError, subprocess.CalledProcessError):
        dirty = unavailable("git status probe failed")

    affinity = (
        value(sorted(os.sched_getaffinity(0)))
        if hasattr(os, "sched_getaffinity")
        else unavailable("not supported")
    )
    evidence = build_evidence()
    dependencies = environment("NMS_BENCHMARK_DEPENDENCIES")
    if not dependencies["available"]:
        dependencies = probe(
            ["dpkg-query", "-W", "-f=${Package}=${Version}\\n", "nlohmann-json3-dev"]
        )
    primary_turbo = read_probe(
        Path("/sys/devices/system/cpu/intel_pstate/no_turbo"),
        "Intel pstate turbo probe was not available",
    )
    fallback_turbo = read_probe(
        Path("/sys/devices/system/cpu/cpufreq/boost"),
        "CPU boost probe was not available",
    )
    turbo = select_turbo_probe(primary_turbo, fallback_turbo)
    virtualization = probe(["systemd-detect-virt"])
    return {
        "repositoryCommit": probe(["git", "rev-parse", "HEAD"]),
        "dirtyWorktree": dirty,
        "benchmarkExecutableSha256": value(
            hashlib.sha256(benchmark.read_bytes()).hexdigest()
        ),
        "serverExecutableSha256": value(
            hashlib.sha256(server.read_bytes()).hexdigest()
        ),
        **evidence,
        "cmakeVersion": probe(["cmake", "--version"]),
        "benchmarkFramework": value(
            {"name": "project-owned-cpp", "version": "1.0.0"}
        ),
        "dependencyVersions": dependencies,
        "operatingSystem": value(platform.platform()),
        "kernel": value(platform.release()),
        "cpuModel": cpu_model,
        "logicalCpuCount": value(os.cpu_count()),
        "cpuAffinity": affinity,
        "frequencyGovernor": read_probe(
            Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "CPU frequency governor probe was not available",
        ),
        "turboBoost": turbo,
        "virtualization": virtualization,
        "pageSize": value(os.sysconf("SC_PAGE_SIZE")),
        "monotonicClock": value(time.get_clock_info("monotonic").implementation),
        "monotonicResolutionSeconds": value(
            time.get_clock_info("monotonic").resolution
        ),
        "schemaVersion": value(SCHEMA_VERSION),
        "fixtureSetVersion": value(FIXTURE_SET_VERSION),
        "harnessVersion": value(HARNESS_VERSION),
        "commandLineArguments": value(argv),
        "noiseControls": {
            "cpuAffinity": "observed-not-pinned",
            "frequencyGovernor": "not-applied",
            "turboBoost": "not-applied",
            "idleSystem": "not-applied",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/benchmark-report.json"),
    )
    args = parser.parse_args()
    if args.output.exists():
        args.output.unlink()
    if not args.fixtures.is_dir():
        fail("fixture directory missing")

    component = json.loads(
        bounded_run(
            [str(args.benchmark), str(args.fixtures.resolve())],
            b"",
            False,
        ).decode()
    )
    component_cases = component.get("cases")
    if not isinstance(component_cases, list):
        fail("component benchmark did not return a case array")
    case_ids = {
        case.get("caseId")
        for case in component_cases
        if isinstance(case, dict)
    }
    required_case_ids = {
        "component.json_sax.valid",
        "component.json_sax.rejected_duplicate",
        "component.json_dom.parse",
        "comparison.protocol.sax_plus_dom",
        "component.runtime_policy.parse",
        "component.proc_text.parse",
    }
    if not required_case_ids.issubset(case_ids):
        fail("required component benchmark cases are missing")
    if os.environ.get("NMS_REQUIRE_STRICT_FILE_CASES") == "1":
        strict_ids = {
            "component.logs.search.streaming",
            "component.logs.tail.streaming",
            "component.elf.inspect",
        }
        if not strict_ids.issubset(case_ids):
            fail("strict log and ELF component cases were silently omitted")

    cases = component_cases + [
        e2e_case(
            "e2e.unconfigured.lifecycle_tools_list",
            args.server,
            False,
            args.fixtures,
            args.output.parent,
        ),
        e2e_case(
            "e2e.configured.all_tools",
            args.server,
            True,
            args.fixtures,
            args.output.parent,
        ),
    ]
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "fixtureSetVersion": FIXTURE_SET_VERSION,
        "harnessVersion": HARNESS_VERSION,
        "framework": component["framework"],
        "outlierPolicy": (
            "All valid samples are retained; no automatic outlier filter is applied."
        ),
        "metadata": metadata(args.benchmark, args.server, sys.argv),
        "cases": cases,
        "comparisonGroups": [
            {
                "id": "protocol.parse",
                "question": (
                    "SAX preflight plus DOM parse versus DOM parse alone "
                    "on identical valid input"
                ),
                "cases": [
                    "component.json_dom.parse",
                    "comparison.protocol.sax_plus_dom",
                ],
                "equivalentInput": True,
                "equivalentResult": True,
                "deploymentRecommendation": "measurement-only",
            }
        ],
        "complete": True,
    }
    encoded = canonical(report).encode()
    if len(encoded) > OUTPUT_LIMIT:
        fail("report byte limit exceeded")

    from validate_benchmark_report import validate

    validate(
        report,
        Path(__file__).resolve().parents[1]
        / "benchmarks/schema/benchmark-report.schema.json",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, args.output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"benchmark failure: {error}", file=sys.stderr)
        raise SystemExit(1)
