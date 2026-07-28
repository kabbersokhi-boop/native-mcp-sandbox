"""Minimal allowlist environment construction for future children."""

from __future__ import annotations

import re
from typing import Mapping

from .errors import FailureClass, ProviderError, failure


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NEVER_ALLOW = {
    "OPENAI_API_KEY", "NVIDIA_API_KEY", "NIM_API_KEY", "API_KEY", "AUTHORIZATION",
    "PROXY_USER", "PROXY_PASSWORD", "SECRET_STORE_TOKEN", "VAULT_TOKEN",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
}
_SECRET_HINTS = ("API_KEY", "TOKEN", "PASSWORD", "SECRET", "AUTH", "CREDENTIAL")
_PROVIDER_HINTS = ("PROVIDER", "OPENAI", "NVIDIA", "NIM", "MODEL_ENDPOINT", "MODEL_URL")


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "invalid child environment variable name"))


def build_child_environment(
    parent: Mapping[str, str],
    allowlist: tuple[str, ...] | list[str],
    *,
    required: Mapping[str, str] | None = None,
    allow_proxy: bool = False,
    max_value_bytes: int = 4_096,
) -> dict[str, str]:
    if not isinstance(max_value_bytes, int) or max_value_bytes <= 0 or max_value_bytes > 64 * 1024:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "environment value limit is invalid"))
    names = list(allowlist)
    for name in names:
        _validate_name(name)
    if len(set(names)) != len(names):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "allowlist contains duplicate names"))
    values = dict(required or {})
    for name in values:
        _validate_name(name)
    if set(values) - set(names):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "required variable is not allowlisted"))
    result: dict[str, str] = {}
    for name in sorted(names):
        upper = name.upper()
        if upper in _NEVER_ALLOW or any(hint in upper for hint in _SECRET_HINTS + _PROVIDER_HINTS):
            if upper in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"} and allow_proxy:
                pass
            else:
                raise ProviderError(failure(FailureClass.LOCAL_POLICY_FAILURE, "secret or provider variable cannot be allowlisted"))
        value = values[name] if name in values else parent.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or len(value.encode("utf-8", "replace")) > max_value_bytes:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "child environment value is invalid or oversized"))
        result[name] = value
    return result
