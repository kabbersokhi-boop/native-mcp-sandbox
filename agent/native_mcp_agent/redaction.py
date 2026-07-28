"""Deterministic structural redaction primitives."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


REDACTED = "<redacted>"
_SECRET_KEYS = {
    "authorization", "proxy-authorization", "api_key", "apikey", "api-key",
    "access_token", "refresh_token", "token", "password", "secret", "credential",
}
_PID_KEYS = {"pid", "process_id", "raw_pid"}


def _bounded(value: str, maximum: int) -> str:
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", "ignore")


def redact_text(text: str, secrets: Sequence[str] = (), *, maximum: int = 4_096) -> str:
    result = _bounded(str(text), maximum)
    unique = sorted({secret for secret in secrets if isinstance(secret, str) and secret}, key=len, reverse=True)
    for secret in unique:
        result = result.replace(secret, REDACTED)
    return _bounded(result, maximum)


def redact_headers(headers: Mapping[str, str], secrets: Sequence[str] = ()) -> dict[str, str]:
    output: dict[str, str] = {}
    for key in sorted(headers, key=lambda item: item.lower()):
        normalized = key.lower()
        if normalized in {"authorization", "proxy-authorization", "cookie", "set-cookie"}:
            output[normalized] = REDACTED
        else:
            output[normalized] = redact_text(headers[key], secrets, maximum=256)
    return output


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return REDACTED
    if parsed.username is None and parsed.password is None:
        return _bounded(url, 512)
    host = parsed.hostname or REDACTED
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, parsed.query, parsed.fragment))


def redact_json(value: Any, secrets: Sequence[str] = (), *, maximum: int = 4_096) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key in sorted(value):
            if str(key).lower() in _SECRET_KEYS or str(key).lower().endswith("_token"):
                output[str(key)] = REDACTED
            elif str(key).lower() in _PID_KEYS:
                output[str(key)] = REDACTED
            else:
                output[str(key)] = redact_json(value[key], secrets, maximum=maximum)
        return output
    if isinstance(value, list):
        return [redact_json(item, secrets, maximum=maximum) for item in value[:128]]
    if isinstance(value, str):
        return redact_text(value, secrets, maximum=maximum)
    return value


def redact_exception(error: BaseException, secrets: Sequence[str] = ()) -> str:
    return redact_text(str(error), secrets, maximum=256)


def redact_provider_excerpt(body: bytes | str, secrets: Sequence[str] = ()) -> str:
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    return redact_text(text, secrets, maximum=256)
