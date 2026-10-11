#!/usr/bin/env python3
"""Make real kernel controls unavailable and verify default startup fails closed."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_boundaries import lifecycle, wire
from stdio_harness import exchange


def verify(server: Path, helper: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="nms-strict-") as directory:
        root = Path(directory)
        policy = root / "policy.json"
        policy.write_bytes(wire({"version": 2, "roots": [
            {"name": "evidence", "path": str(root), "maxFileBytes": 65536}],
            "processes": [{"name": "server", "pid": "self"}]}))
        for control, flag in (("openat2", "--allow-legacy-descriptor-walk"),
                              ("pidfd_open", "--allow-legacy-process-pinning")):
            command = [str(helper.resolve()), control, str(server.resolve()), "--policy-config", str(policy)]
            payload = lifecycle() + wire({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            strict = exchange(command, payload)
            assert strict.status == 78, f"{control}: expected fail-closed status 78, got {strict.status}: {strict.stderr!r}"
            assert not strict.stdout, f"{control}: unavailable strict control must not advertise tools"
            explicit = exchange([*command, flag], payload)
            assert explicit.status == 0, f"{control}: explicit compatibility failed: {explicit.stderr!r}"
            messages = [json.loads(line) for line in explicit.stdout.splitlines()]
            listing = next(item["result"] for item in messages if item["id"] == 2)
            assert len(listing["tools"]) == 4
            assert b"warning: legacy" in explicit.stderr
            print(f"PASS {control}: strict startup rejects; explicit compatibility warns")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--helper", required=True, type=Path)
    arguments = parser.parse_args()
    verify(arguments.server, arguments.helper)
