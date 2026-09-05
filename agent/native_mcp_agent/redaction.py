"""Deterministic, bounded redaction primitives.

Redaction happens before a byte bound is selected.  This ordering is
intentional: a secret crossing the output boundary must never leave a prefix
behind.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

REDACTED = "<redacted>"
_SECRET_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "api-key",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "secret",
    "credential",
}
_PATH_KEYS = {"path", "file_path", "absolute_path", "cwd", "working_directory", "executable"}
_PID_KEYS = {"pid", "process_id", "raw_pid", "process-id"}
_HEADER_RE = re.compile(r"(?is)\b(?:proxy-authorization|authorization|cookie)\s*:\s*[^\r\n]*")
_BEARER_RE = re.compile(r"(?is)\bbearer\s+[A-Za-z0-9._~+/=-]{4,}")
_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\x00-\x1f\\]|\\)+")
_PID_ASSIGNMENT_RE = re.compile(r"(?i)\b(?:pid|raw_pid|process[_-]?id)\s*[=:]\s*\d+\b")
_SECRET_VALUE_RE = re.compile(r"(?i)\b(?:api[_-]?key|secret(?:[_-]?store)?|token)[A-Za-z0-9_.=-]*")
_USERINFO_URL_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s]+")
_DIAGNOSTIC_KEYS = {
    "diagnostic",
    "detail",
    "error",
    "message",
    "command",
    "argv",
    "output",
    "stdout",
    "stderr",
}


def _bounded(value: str, maximum: int) -> str:
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", "ignore")


def _secret_spans(text: str, secrets: Sequence[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for secret in secrets:
        if not isinstance(secret, str) or not secret:
            continue
        start = 0
        while True:
            index = text.find(secret, start)
            if index < 0:
                break
            spans.append((index, index + len(secret)))
            start = index + 1  # retain overlapping occurrences
    return spans


def _replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    output: list[str] = []
    cursor = 0
    for start, end in merged:
        output.append(text[cursor:start])
        output.append(REDACTED)
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _structural_text(text: str, *, sensitive_field: bool = False) -> str:
    spans: list[tuple[int, int]] = []
    if sensitive_field:
        spans.extend(match.span() for match in _HEADER_RE.finditer(text))
        spans.extend(match.span() for match in _BEARER_RE.finditer(text))
        spans.extend(match.span() for match in _ABSOLUTE_PATH_RE.finditer(text))
        spans.extend(match.span() for match in _PID_ASSIGNMENT_RE.finditer(text))
        spans.extend(match.span() for match in _SECRET_VALUE_RE.finditer(text))
        spans.extend(match.span() for match in _USERINFO_URL_RE.finditer(text))
    return _replace_spans(text, spans)


def redact_text(text: str, secrets: Sequence[str] = (), *, maximum: int = 4_096) -> str:
    """Redact configured and structurally recognizable secrets before truncation."""
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        return REDACTED
    if not isinstance(text, str):
        return REDACTED
    # The configured spans are merged, including overlaps, so neither a full
    # secret nor a fragment of one can survive the final byte truncation.
    result = _replace_spans(text, _secret_spans(text, secrets))
    return _bounded(result, maximum)


def _redact_sensitive_text(text: str, secrets: Sequence[str], maximum: int) -> str:
    if not isinstance(text, str):
        return REDACTED
    result = redact_text(text, secrets, maximum=max(maximum, len(text.encode("utf-8", "replace"))))
    return _bounded(_structural_text(result, sensitive_field=True), maximum)


def redact_headers(headers: Mapping[str, str], secrets: Sequence[str] = ()) -> dict[str, str]:
    output: dict[str, str] = {}
    if not isinstance(headers, Mapping):
        return {"<invalid>": REDACTED}
    for key in sorted(headers, key=lambda item: str(item).lower()):
        normalized = str(key).lower()
        if normalized in {"authorization", "proxy-authorization", "cookie", "set-cookie"}:
            output[normalized] = REDACTED
        else:
            output[normalized] = _redact_sensitive_text(headers[key], secrets, 256)
    return output


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        if parsed is None or parsed.hostname is None:
            return REDACTED
        # Query and fragment values are untrusted too; preserve only the
        # scheme, authority host/port, and path after removing user-info.
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return _bounded(f"{parsed.scheme}://{host}{port}{parsed.path or '/'}", 512)
    except (ValueError, TypeError):
        return REDACTED


def redact_json(value: Any, secrets: Sequence[str] = (), *, maximum: int = 4_096) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            normalized = str(key).lower()
            if (
                normalized in _SECRET_KEYS
                or normalized.endswith("_token")
                or normalized in _PID_KEYS
                or normalized in _PATH_KEYS
            ):
                output[str(key)] = REDACTED
            elif isinstance(value[key], str):
                if normalized in _DIAGNOSTIC_KEYS:
                    output[str(key)] = _redact_sensitive_text(value[key], secrets, maximum)
                else:
                    output[str(key)] = redact_text(value[key], secrets, maximum=maximum)
            else:
                output[str(key)] = redact_json(value[key], secrets, maximum=maximum)
        return output
    if isinstance(value, (list, tuple)):
        return [redact_json(item, secrets, maximum=maximum) for item in value[:128]]
    if isinstance(value, str):
        return redact_text(value, secrets, maximum=maximum)
    return value


def redact_exception(error: BaseException, secrets: Sequence[str] = ()) -> str:
    try:
        text = str(error)
    except Exception:
        text = REDACTED
    return _redact_sensitive_text(text, secrets, 256)


def redact_provider_excerpt(body: bytes | str, secrets: Sequence[str] = ()) -> str:
    try:
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    except (AttributeError, UnicodeError):
        text = REDACTED
    return _redact_sensitive_text(text, secrets, 256)
