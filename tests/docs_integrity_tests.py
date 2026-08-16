#!/usr/bin/env python3
"""Small, dependency-free checks for the public documentation surface."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (
    ROOT / "README.md",
    ROOT / "ARCHITECTURE.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "ASSURANCE.md",
)
REQUIRED_PUBLIC_DOCS = CURRENT_DOCS + (
    ROOT / "THREAT_MODEL.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "DEMO.md",
    ROOT / "docs" / "ENGINEERING_HIGHLIGHTS.md",
    ROOT / "docs" / "RELEASING.md",
)
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
VERSION = re.compile(r"\bVERSION\s+(\d+\.\d+\.\d+)\b")


def fail(message: str) -> None:
    print(f"docs-integrity: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_relative_links() -> None:
    for document in ROOT.rglob("*.md"):
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            destination = (document.parent / target).resolve()
            try:
                destination.relative_to(ROOT)
            except ValueError:
                fail(f"{document.relative_to(ROOT)} links outside the repository: {target}")
            if not destination.exists():
                fail(f"{document.relative_to(ROOT)} has a missing relative link: {target}")


def check_current_version() -> None:
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    match = VERSION.search(cmake)
    if match is None:
        fail("CMakeLists.txt has no project version")
    version = match.group(1)
    tag = f"v{version}"
    for document in REQUIRED_PUBLIC_DOCS:
        if not document.exists():
            fail(f"required public document is missing: {document.relative_to(ROOT)}")
    for document in CURRENT_DOCS:
        if tag not in document.read_text(encoding="utf-8"):
            fail(f"{document.relative_to(ROOT)} does not mention current release {tag}")
    expected_version_files = (
        ROOT / "scripts" / "run_agent_investigation_demo.py",
        ROOT / "demo" / "investigation" / "expected-report.json",
        ROOT / "tests" / "foundation_tests.cpp",
        ROOT / "tests" / "protocol_tests.cpp",
        ROOT / "tests" / "stdio_integration_tests.cpp",
    )
    for path in expected_version_files:
        if version not in path.read_text(encoding="utf-8"):
            fail(f"{path.relative_to(ROOT)} does not match project version {version}")


def main() -> None:
    check_relative_links()
    check_current_version()
    print("docs-integrity: passed")


if __name__ == "__main__":
    main()
