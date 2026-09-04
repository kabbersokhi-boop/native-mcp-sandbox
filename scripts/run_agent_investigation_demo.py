#!/usr/bin/env python3
"""Run the deterministic deterministic demonstration investigation demonstration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import selectors
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


VERSION = "0.11.0"
CORRELATION_ID = "INC-042"
EXPECTED_TOOLS = ["logs.search", "logs.tail", "elf.inspect", "proc.memory"]
FIXTURE_SIZE_LIMIT = 64 * 1024
PROTOCOL_OUTPUT_LIMIT = 256 * 1024
STDERR_LIMIT = 64 * 1024
TIMEOUT_SECONDS = 20.0
ELF_NAME = "sample.elf"
LOG_NAME = "application.log"
ROOT_NAME = "evidence"


class DemoError(RuntimeError):
    """The demonstration did not satisfy a deterministic check."""


def fail(message: str) -> None:
    raise DemoError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_nonnegative_integer(value: Any) -> bool:
    return is_integer(value) and value >= 0


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def write_utf8(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def write_minimal_elf(path: Path) -> None:
    """Write a valid, non-executable ELF64 header with no program headers."""

    identity = bytearray(16)
    identity[0:4] = b"\x7fELF"
    identity[4] = 2  # ELFCLASS64
    identity[5] = 1  # ELFDATA2LSB
    identity[6] = 1  # EV_CURRENT
    identity[7] = 3  # ELFOSABI_LINUX
    header = struct.pack(
        "<16sHHIQQQIHHHHHH",
        bytes(identity),
        2,  # ET_EXEC
        62,  # EM_X86_64
        1,  # EV_CURRENT
        0,  # entry point
        0,  # program-header offset
        0,  # section-header offset
        0,  # flags
        64,  # ELF header size
        56,  # program-header entry size
        0,  # program-header count
        0,  # section-header entry size
        0,  # section-header count
        0,  # section-name string-table index
    )
    require(len(header) == 64, "generated ELF header has an unexpected size")
    path.write_bytes(header)
    os.chmod(path, 0o600)


def copy_fixture(fixture: Path, root: Path) -> Path:
    require(fixture.is_file(), "the committed log fixture is not a regular file")
    size = fixture.stat().st_size
    require(size <= FIXTURE_SIZE_LIMIT, "the committed log fixture exceeds its limit")
    destination = root / LOG_NAME
    shutil.copyfile(fixture, destination)
    os.chmod(destination, 0o600)
    require(destination.stat().st_size == size, "the copied log fixture changed size")
    return destination


def make_policy(root: Path) -> Path:
    policy = {
        "version": 2,
        "roots": [
            {"name": ROOT_NAME, "path": str(root), "maxFileBytes": FIXTURE_SIZE_LIMIT}
        ],
        "processes": [{"name": "server", "pid": "self"}],
    }
    path = root / "policy.json"
    write_utf8(path, stable_json(policy) + "\n")
    os.chmod(path, 0o600)
    return path


def request(request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def tool_request(
    request_id: int, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    return request(request_id, "tools/call", {"name": name, "arguments": arguments})


def build_protocol_input() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    initialize_params = {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "deterministic-demo", "version": VERSION},
    }
    tool_calls = [
        tool_request(
            10,
            "logs.search",
            {
                "root": ROOT_NAME,
                "path": LOG_NAME,
                "query": CORRELATION_ID,
                "caseSensitive": True,
                "maxMatches": 10,
            },
        ),
        tool_request(
            11,
            "logs.search",
            {
                "root": ROOT_NAME,
                "path": LOG_NAME,
                "query": "ERROR",
                "caseSensitive": True,
                "maxMatches": 10,
            },
        ),
        tool_request(
            12, "logs.tail", {"root": ROOT_NAME, "path": LOG_NAME, "maxLines": 3}
        ),
        tool_request(13, "elf.inspect", {"root": ROOT_NAME, "path": ELF_NAME}),
        tool_request(14, "proc.memory", {"process": "server"}),
    ]
    messages: list[dict[str, Any]] = [
        request(1, "initialize", initialize_params),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request(2, "tools/list", {}),
        *tool_calls,
    ]
    lines = "\n".join(stable_json(message) for message in messages) + "\n"
    return lines, messages, tool_calls


def terminate_child(process: subprocess.Popen[bytes]) -> None:
    """Kill and reap a child after a bounded-read failure."""

    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def read_streams_bounded(
    process: subprocess.Popen[bytes], protocol_input: bytes
) -> tuple[bytes, bytes]:
    """Read both child streams with fixed bounds and a monotonic deadline."""

    require(process.stdin is not None, "server standard input is not available")
    try:
        process.stdin.write(protocol_input)
        process.stdin.close()
    except (BrokenPipeError, OSError) as error:
        terminate_child(process)
        fail(f"failed to write protocol input: {error}")

    selector = selectors.DefaultSelector()
    stdout_data = bytearray()
    stderr_data = bytearray()
    streams = (
        (process.stdout, stdout_data, PROTOCOL_OUTPUT_LIMIT, "protocol output"),
        (process.stderr, stderr_data, STDERR_LIMIT, "standard error"),
    )
    try:
        for stream, buffer, limit, label in streams:
            require(stream is not None, f"{label} stream is not available")
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, (buffer, limit, label))

        deadline = time.monotonic() + TIMEOUT_SECONDS
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                fail(f"server timed out after {TIMEOUT_SECONDS:.1f} seconds")
            events = selector.select(remaining)
            if not events:
                if process.poll() is None:
                    fail(f"server timed out after {TIMEOUT_SECONDS:.1f} seconds")
                continue
            for key, _ in events:
                stream = key.fileobj
                buffer, limit, label = key.data
                current_size = len(buffer)
                read_size = min(8192, max(1, limit - current_size + 1))
                try:
                    chunk = os.read(stream.fileno(), read_size)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                if current_size + len(chunk) > limit:
                    fail(f"{label} exceeded its byte limit")
                buffer.extend(chunk)
                if label == "standard error":
                    fail("strict execution wrote unexpected standard error")
        return bytes(stdout_data), bytes(stderr_data)
    except (DemoError, OSError):
        terminate_child(process)
        raise
    finally:
        selector.close()


def run_server(
    server: Path, policy: Path, protocol_input: str
) -> dict[int, dict[str, Any]]:
    command = [str(server), "--policy-config", str(policy)]
    require(
        "--allow-legacy-descriptor-walk" not in command,
        "legacy filesystem mode was requested",
    )
    require(
        "--allow-legacy-process-pinning" not in command,
        "legacy process mode was requested",
    )
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C", "TZ": "UTC"})
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    try:
        stdout, stderr = read_streams_bounded(process, protocol_input.encode("utf-8"))
    except (DemoError, OSError):
        terminate_child(process)
        raise
    require(stderr == b"", "strict execution wrote unexpected standard error")
    require(process.returncode == 0, f"server exited with status {process.returncode}")
    try:
        decoded = stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        fail(f"protocol output is not valid UTF-8: {error}")
    require(decoded.endswith("\n"), "protocol output must end with a newline")
    lines = decoded.splitlines()
    require(all(line for line in lines), "protocol output contains a blank line")
    responses: dict[int, dict[str, Any]] = {}
    expected_ids = {1, 2, 10, 11, 12, 13, 14}
    for line in lines:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            fail(f"protocol output contains invalid JSON: {error}")
        require(isinstance(message, dict), "protocol response is not an object")
        response_id = message.get("id")
        require(is_integer(response_id), "protocol response has an invalid request ID")
        require(
            response_id not in responses,
            "protocol output contains a duplicate response ID",
        )
        require(
            response_id in expected_ids,
            "protocol output contains an unexpected response ID",
        )
        require("error" not in message, "server returned a JSON-RPC error")
        responses[response_id] = message
    require(set(responses) == expected_ids, "protocol output is missing a response")
    return responses


def result_content(response: dict[str, Any], label: str) -> dict[str, Any]:
    require(
        set(response) == {"id", "jsonrpc", "result"},
        f"{label} response has an unexpected schema",
    )
    require(
        response["jsonrpc"] == "2.0",
        f"{label} response has an unexpected JSON-RPC version",
    )
    result = response["result"]
    require(isinstance(result, dict), f"{label} result is not an object")
    require(
        set(result) == {"content", "isError", "structuredContent"},
        f"{label} result has an unexpected schema",
    )
    require(result["isError"] is False, f"{label} returned a tool execution error")
    content = result["content"]
    structured = result["structuredContent"]
    require(
        isinstance(content, list) and len(content) == 1, f"{label} content is invalid"
    )
    require(
        isinstance(content[0], dict) and content[0].get("type") == "text",
        f"{label} text content is invalid",
    )
    require(
        isinstance(content[0].get("text"), str), f"{label} text content is not a string"
    )
    try:
        text_content = json.loads(content[0]["text"])
    except json.JSONDecodeError as error:
        fail(f"{label} text content is invalid JSON: {error}")
    require(text_content == structured, f"{label} text and structured content differ")
    require(
        isinstance(structured, dict), f"{label} structured content is not an object"
    )
    return structured


def validate_log_common(value: dict[str, Any], expected_bytes: int, label: str) -> None:
    require(value.get("root") == ROOT_NAME, f"{label} returned an unexpected root")
    require(value.get("path") == LOG_NAME, f"{label} returned an unexpected path")
    require(
        is_nonnegative_integer(value.get("bytesScanned")),
        f"{label} bytesScanned has an invalid type",
    )
    require(
        value["bytesScanned"] == expected_bytes,
        f"{label} scanned an unexpected byte count",
    )
    require(
        is_nonnegative_integer(value.get("linesScanned")),
        f"{label} linesScanned has an invalid type",
    )
    require(value["linesScanned"] == 5, f"{label} scanned an unexpected line count")
    require(
        value.get("fileChangedDuringRead") is False, f"{label} reported a changed file"
    )


def validate_search(
    value: dict[str, Any],
    expected_bytes: int,
    expected_lines: list[int],
    expected_previews: list[str],
    label: str,
) -> None:
    validate_log_common(value, expected_bytes, label)
    require(
        value.get("caseSensitive") is True,
        f"{label} did not use case-sensitive matching",
    )
    require(value.get("matchLimitReached") is False, f"{label} reached its match limit")
    matches = value.get("matches")
    require(
        isinstance(matches, list) and len(matches) == len(expected_lines),
        f"{label} returned an unexpected match count",
    )
    for match, line_number, preview in zip(matches, expected_lines, expected_previews):
        require(isinstance(match, dict), f"{label} returned a malformed match")
        require(
            match.get("line") == line_number,
            f"{label} returned an unexpected line number",
        )
        require(
            is_nonnegative_integer(match.get("byteOffset")),
            f"{label} returned an invalid byte offset",
        )
        require(
            match.get("preview") == preview, f"{label} returned an unexpected preview"
        )
        require(
            match.get("previewTruncatedStart") is False,
            f"{label} truncated the start of a preview",
        )
        require(
            match.get("previewTruncatedEnd") is False,
            f"{label} truncated the end of a preview",
        )


def validate_tail(
    value: dict[str, Any],
    expected_bytes: int,
    expected_lines: list[int],
    expected_previews: list[str],
) -> None:
    validate_log_common(value, expected_bytes, "logs.tail")
    lines = value.get("lines")
    require(
        isinstance(lines, list) and len(lines) == 3,
        "logs.tail returned an unexpected line count",
    )
    for line, line_number, preview in zip(lines, expected_lines, expected_previews):
        require(isinstance(line, dict), "logs.tail returned a malformed line")
        require(
            line.get("line") == line_number,
            "logs.tail returned an unexpected line number",
        )
        require(
            is_nonnegative_integer(line.get("byteOffset")),
            "logs.tail returned an invalid byte offset",
        )
        require(
            line.get("preview") == preview, "logs.tail returned an unexpected preview"
        )
        require(
            line.get("previewTruncatedStart") is False, "logs.tail truncated a preview"
        )


def validate_elf(value: dict[str, Any]) -> None:
    require(value.get("root") == ROOT_NAME, "elf.inspect returned an unexpected root")
    require(value.get("path") == ELF_NAME, "elf.inspect returned an unexpected path")
    require(
        value.get("class") == "ELF64", "elf.inspect returned an unexpected ELF class"
    )
    require(
        value.get("endianness") == "little",
        "elf.inspect returned an unexpected byte order",
    )
    require(
        value.get("fileType") == "executable",
        "elf.inspect returned an unexpected file type",
    )
    require(
        value.get("fileTypeNumber") == 2,
        "elf.inspect returned an unexpected file type number",
    )
    require(
        value.get("machine") == "x86_64", "elf.inspect returned an unexpected machine"
    )
    require(
        value.get("machineNumber") == 62,
        "elf.inspect returned an unexpected machine number",
    )
    require(value.get("osAbi") == "linux", "elf.inspect returned an unexpected OS ABI")
    require(
        value.get("osAbiNumber") == 3,
        "elf.inspect returned an unexpected OS ABI number",
    )
    require(
        value.get("entryPoint") == "0x0",
        "elf.inspect returned an unexpected entry point",
    )
    require(
        value.get("programHeaderCount") == 0,
        "elf.inspect returned unexpected program headers",
    )
    require(
        value.get("interpreter") is None,
        "elf.inspect returned an unexpected interpreter",
    )
    require(
        value.get("neededLibraries") == [], "elf.inspect returned unexpected libraries"
    )
    require(
        value.get("neededLibrariesTruncated") is False,
        "elf.inspect truncated libraries",
    )
    require(value.get("buildId") is None, "elf.inspect returned an unexpected build ID")
    require(
        value.get("stackPolicy") == "unspecified",
        "elf.inspect returned an unexpected stack policy",
    )
    require(
        value.get("relro") == "none", "elf.inspect returned an unexpected RELRO state"
    )
    require(
        value.get("positionIndependent") is False,
        "elf.inspect returned an unexpected PIE signal",
    )
    require(
        value.get("pieExecutable") is False,
        "elf.inspect returned an unexpected PIE executable signal",
    )
    require(
        value.get("writableExecutableLoadSegment") is False,
        "elf.inspect returned an unexpected segment signal",
    )
    require(
        value.get("fileChangedDuringRead") is False,
        "elf.inspect reported a changed file",
    )
    require(
        is_nonnegative_integer(value.get("metadataBytesRead")),
        "elf.inspect returned an invalid metadata byte count",
    )
    require(value.get("segments") == [], "elf.inspect returned unexpected segments")
    require(
        value.get("segmentSummariesTruncated") is False,
        "elf.inspect truncated segments",
    )


def validate_process(value: dict[str, Any]) -> None:
    require(
        value.get("process") == "server",
        "proc.memory returned an unexpected process alias",
    )
    require(
        is_integer(value.get("pid")) and value["pid"] > 0,
        "proc.memory returned an invalid PID",
    )
    require(
        is_integer(value.get("uid")) and value["uid"] >= 0,
        "proc.memory returned an invalid UID",
    )
    require(
        isinstance(value.get("name"), str) and value["name"],
        "proc.memory returned an invalid process name",
    )
    require(
        isinstance(value.get("state"), str) and value["state"],
        "proc.memory returned an invalid process state",
    )
    require(
        is_nonnegative_integer(value.get("threads")),
        "proc.memory returned an invalid thread count",
    )
    require(
        is_integer(value.get("pageSizeBytes")) and value["pageSizeBytes"] > 0,
        "proc.memory returned an invalid page size",
    )
    require(
        value.get("pidfdPinned") is True,
        "proc.memory did not report strict pidfd pinning",
    )
    status = value.get("status")
    require(isinstance(status, dict), "proc.memory status counters are missing")
    for counter in (
        "vmSizeBytes",
        "vmRssBytes",
        "rssAnonBytes",
        "rssFileBytes",
        "rssShmemBytes",
    ):
        require(
            is_nonnegative_integer(status.get(counter)),
            f"proc.memory counter {counter} is missing",
        )
    statm = value.get("statm")
    require(isinstance(statm, dict), "proc.memory statm counters are missing")
    for counter in (
        "virtualBytes",
        "residentBytes",
        "sharedBytes",
        "textBytes",
        "dataAndStackBytes",
    ):
        require(
            is_nonnegative_integer(statm.get(counter)),
            f"proc.memory counter {counter} is missing",
        )
    require(
        isinstance(value.get("smapsRollupAvailable"), bool),
        "proc.memory rollup availability has an invalid type",
    )
    require(
        value.get("smapsRollupError") is None
        or isinstance(value.get("smapsRollupError"), str),
        "proc.memory rollup error has an invalid type",
    )


def report(
    responses: dict[int, dict[str, Any]],
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    log_bytes: bytes,
) -> dict[str, Any]:
    lines = log_bytes.decode("utf-8").splitlines()
    validate_initialize = responses[1]
    require(
        validate_initialize["result"]["serverInfo"]["version"] == VERSION,
        "server reported an unexpected version",
    )
    require(
        [tool["name"] for tool in responses[2]["result"]["tools"]] == EXPECTED_TOOLS,
        "server returned an unexpected tool list",
    )
    correlation = result_content(responses[10], "correlation search")
    errors = result_content(responses[11], "error search")
    tail = result_content(responses[12], "tail")
    elf = result_content(responses[13], "ELF inspection")
    process = result_content(responses[14], "process observation")
    validate_search(
        correlation, len(log_bytes), [1, 2, 3, 4, 5], lines, "correlation search"
    )
    validate_search(errors, len(log_bytes), [2], [lines[1]], "error search")
    validate_tail(tail, len(log_bytes), [3, 4, 5], lines[2:])
    validate_elf(elf)
    validate_process(process)
    request_records = []
    for message in messages:
        if "id" in message:
            request_records.append(
                {
                    "arguments": message.get("params", {}),
                    "method": message["method"],
                    "requestId": message["id"],
                }
            )
    evidence = [
        {
            "arguments": tool_calls[0]["params"]["arguments"],
            "finding": {"expectedLines": [1, 2, 3, 4, 5], "matchCount": 5},
            "requestId": 10,
            "tool": "logs.search",
        },
        {
            "arguments": tool_calls[1]["params"]["arguments"],
            "finding": {"expectedLines": [2], "matchCount": 1},
            "requestId": 11,
            "tool": "logs.search",
        },
        {
            "arguments": tool_calls[2]["params"]["arguments"],
            "finding": {"expectedLines": [3, 4, 5], "finalState": "healthy"},
            "requestId": 12,
            "tool": "logs.tail",
        },
        {
            "arguments": tool_calls[3]["params"]["arguments"],
            "finding": {
                "elfClass": "ELF64",
                "machine": "x86_64",
                "fileType": "executable",
            },
            "requestId": 13,
            "tool": "elf.inspect",
        },
        {
            "arguments": tool_calls[4]["params"]["arguments"],
            "finding": {
                "observed": True,
                "requiredAggregateCountersPresent": True,
                "strictPidfdPinning": True,
            },
            "requestId": 14,
            "tool": "proc.memory",
        },
    ]
    return {
        "conclusion": "healthy_final_state_confirmed",
        "evidence": evidence,
        "investigation": {
            "correlationId": CORRELATION_ID,
            "scenario": "service_restart_authentication_recovery",
            "version": VERSION,
        },
        "requests": request_records,
        "schemaVersion": 1,
        "security": {
            "legacyFlagsPassed": False,
            "strictOpenat2": True,
            "strictPidfdPinning": True,
        },
    }


def write_reports(output_dir: Path, canonical: dict[str, Any]) -> None:
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_text = (
        json.dumps(canonical, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    )
    markdown = """# Agent investigation report

## Conclusion

The investigation confirms a healthy final state for correlation `INC-042`.

## Requests

The client used request IDs `1` and `2` for the MCP lifecycle.
The client used request IDs `10` through `14` for the fixed tool sequence.

| Request ID | Tool | Fixed arguments |
| ---: | --- | --- |
| 10 | `logs.search` | `root=evidence`, `path=application.log`, `query=INC-042`, `caseSensitive=true`, `maxMatches=10` |
| 11 | `logs.search` | `root=evidence`, `path=application.log`, `query=ERROR`, `caseSensitive=true`, `maxMatches=10` |
| 12 | `logs.tail` | `root=evidence`, `path=application.log`, `maxLines=3` |
| 13 | `elf.inspect` | `root=evidence`, `path=sample.elf` |
| 14 | `proc.memory` | `process=server` |

## Evidence

1. The correlation search found five expected lines.
2. The error search found one authentication failure.
3. The final three lines show a bounded retry, authentication recovery, and a healthy state.
4. The ELF inspection found the expected ELF64 x86_64 executable identity.
5. The process observation succeeded with strict pidfd pinning and the required aggregate counters.

## Limits

- The client used only the four existing MCP tools.
- The server ran in strict mode without legacy compatibility flags.
- The client used one committed log fixture and one generated non-executable ELF fixture.
- The client did not execute or import the generated ELF file.
- The reports contain stable predicates only. They do not contain runtime process values or temporary paths.
- The JSON and Markdown output use fixed order and one final newline.

## Non-claims

- This demonstration is not autonomous incident response.
- This demonstration is not a production agent framework.
- This demonstration is not proof of complete correctness or security.
- This demonstration is one bounded investigation over synthetic data.
"""
    atomic_write_text(json_path, json_text)
    atomic_write_text(markdown_path, markdown)


def atomic_write_text(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def remove_old_reports(output_dir: Path) -> None:
    for name in ("report.json", "report.md"):
        try:
            (output_dir / name).unlink()
        except FileNotFoundError:
            pass


def run_demo(server: Path, fixture: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    require(output_dir.is_dir(), "the output directory is not a directory")
    remove_old_reports(output_dir)
    require(server.is_file(), "the server executable is not a regular file")
    root = Path(
        tempfile.mkdtemp(prefix="native-mcp-investigation-", dir=str(output_dir))
    )
    try:
        log_path = copy_fixture(fixture, root)
        elf_path = root / ELF_NAME
        write_minimal_elf(elf_path)
        policy = make_policy(root)
        protocol_input, messages, tool_calls = build_protocol_input()
        responses = run_server(server, policy, protocol_input)
        canonical = report(responses, messages, tool_calls, log_path.read_bytes())
        require(
            canonical["conclusion"] == "healthy_final_state_confirmed",
            "the investigation conclusion changed",
        )
        write_reports(output_dir, canonical)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        run_demo(
            arguments.server.resolve(),
            arguments.fixture.resolve(),
            arguments.output_dir.resolve(),
        )
    except (DemoError, OSError, ValueError) as error:
        print(f"agent investigation demo failed: {error}", file=sys.stderr)
        return 1
    print("agent investigation demo passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
