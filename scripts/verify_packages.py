#!/usr/bin/env python3
"""Install both release artifacts away from the checkout and verify their demo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def verify(native_package: Path, wheel: Path, output: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for isolated package verification")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME"}}
    with tempfile.TemporaryDirectory(prefix="nms-packages-") as directory:
        root = Path(directory)
        with tarfile.open(native_package) as archive:
            archive.extractall(root / "native", filter="data")
        binaries = list((root / "native").rglob("bin/native-mcp-sandbox"))
        if len(binaries) != 1:
            raise RuntimeError("native archive must contain exactly one server executable")
        venv = root / "venv"
        subprocess.run([uv, "venv", "--python", sys.executable, str(venv)],
                       cwd=root, env=environment, check=True, timeout=60)
        subprocess.run([uv, "pip", "install", "--no-index", "--python", str(venv / "bin/python"),
                        str(wheel.resolve())], cwd=root, env=environment, check=True, timeout=60)
        subprocess.run([str(venv / "bin/native-mcp-agent"), "demo", "--server", str(binaries[0]),
                        "--output", str(root / "reports")], cwd=root, env=environment,
                       check=True, timeout=60)
        reports = {name: json.loads((root / "reports" / name / "report.json").read_text())
                   for name in ("recovered", "inconclusive", "hostile")}
        expected = {"recovered": "recovery-observed", "inconclusive": "inconclusive", "hostile": "boundary-held"}
        for name, result in expected.items():
            if reports[name]["result"] != result:
                raise RuntimeError("installed package scenario returned an unexpected result")
        record = {"schemaVersion": 1, "passed": True, "results": expected,
                  "nativePackageSha256": hashlib.sha256(native_package.read_bytes()).hexdigest(),
                  "wheelSha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  "execution": "installed wheel and extracted native archive in a temporary directory; no checkout imports"}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-package", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/package-verification.json"))
    arguments = parser.parse_args()
    verify(arguments.native_package, arguments.wheel, arguments.output)
