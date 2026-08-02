"""Minimal allowlist environment construction for future children."""

from __future__ import annotations

import re
import ipaddress
from typing import Mapping
from urllib.parse import urlsplit

from .errors import FailureClass, ProviderError, failure


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NEVER_ALLOW = {
    "OPENAI_API_KEY", "NVIDIA_API_KEY", "NIM_API_KEY", "API_KEY", "AUTHORIZATION",
    "PROXY_USER", "PROXY_PASSWORD", "SECRET_STORE_TOKEN", "VAULT_TOKEN",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
}
_SECRET_HINTS = ("API_KEY", "TOKEN", "PASSWORD", "SECRET", "AUTH", "CREDENTIAL")
_PROVIDER_HINTS = ("PROVIDER", "OPENAI", "NVIDIA", "NIM", "MODEL_ENDPOINT", "MODEL_URL")
_PROXY_NAMES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
_NO_PROXY_NAME = "NO_PROXY"
_DNS_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "invalid child environment variable name"))


def _valid_dns_name(value: str) -> bool:
    return bool(_DNS_NAME.fullmatch(value)) and len(value.encode("ascii", "ignore")) <= 253


def _validate_proxy(value: str) -> None:
    if not isinstance(value, str) or not value.isascii() or any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "proxy value is invalid"))
    if any(char in value for char in ("@", "\\", "?", "#")):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "proxy value is invalid"))
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, UnicodeError):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "proxy value is invalid")) from None
    if parsed.scheme.lower() not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "proxy value is invalid"))
    if not parsed.hostname or port is None or not 1 <= port <= 65535 or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "proxy value is invalid"))
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        valid_host = True
    except ValueError:
        valid_host = _valid_dns_name(host)
    if not valid_host:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "proxy value is invalid"))


def _validate_no_proxy(value: str) -> None:
    if not isinstance(value, str) or not value.isascii() or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
    entries = value.split(",")
    if not entries or len(entries) > 64 or any(not entry for entry in entries):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
    for entry in entries:
        if entry == "*":
            continue
        if "://" in entry or "@" in entry or "/" in entry or "\\" in entry or "?" in entry or "#" in entry:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
        host = entry
        port: str | None = None
        if entry.startswith("["):
            closing = entry.find("]")
            if closing < 0:
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
            host = entry[1:closing]
            remainder = entry[closing + 1:]
            if remainder:
                if not remainder.startswith(":"):
                    raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
                port = remainder[1:]
            try:
                ipaddress.IPv6Address(host)
            except ValueError:
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid")) from None
        else:
            if entry.count(":") > 1:
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
            if ":" in entry:
                host, port = entry.rsplit(":", 1)
            host_value = host[1:] if host.startswith(".") else host
            try:
                ipaddress.IPv4Address(host_value)
                valid_host = host == host_value
            except ValueError:
                valid_host = _valid_dns_name(host_value) and (host.startswith(".") or not host.startswith("."))
            if not valid_host:
                raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))
        if port is not None and (not re.fullmatch(r"[0-9]+", port) or not 1 <= int(port) <= 65535):
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "NO_PROXY value is invalid"))


def build_child_environment(
    parent: Mapping[str, str],
    allowlist: tuple[str, ...] | list[str],
    *,
    required: Mapping[str, str] | None = None,
    allow_proxy: bool = False,
    provider_child: bool = True,
    max_value_bytes: int = 4_096,
) -> dict[str, str]:
    if not isinstance(max_value_bytes, int) or isinstance(max_value_bytes, bool) or max_value_bytes <= 0 or max_value_bytes > 64 * 1024:
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "environment value limit is invalid"))
    if not isinstance(provider_child, bool) or (allow_proxy and provider_child):
        raise ProviderError(failure(FailureClass.LOCAL_POLICY_FAILURE, "proxy allowlisting is only for non-provider children"))
    if not isinstance(parent, Mapping):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "parent environment is invalid"))
    for inherited_name, inherited_value in parent.items():
        _validate_name(inherited_name)
        if not isinstance(inherited_value, str) or "\x00" in inherited_value:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "inherited environment value is invalid"))
    if not isinstance(allowlist, (tuple, list)) or isinstance(allowlist, str):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "child environment allowlist is invalid"))
    names = list(allowlist)
    for name in names:
        _validate_name(name)
    if len(set(names)) != len(names):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "allowlist contains duplicate names"))
    if required is not None and not isinstance(required, Mapping):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "required environment values are invalid"))
    try:
        values = dict(required or {})
    except (TypeError, ValueError):
        raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "required environment values are invalid")) from None
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
        if not isinstance(value, str) or "\x00" in value:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "child environment value is invalid or oversized"))
        if len(value.encode("utf-8")) > max_value_bytes:
            raise ProviderError(failure(FailureClass.LOCAL_VALIDATION_FAILURE, "child environment value is invalid or oversized"))
        if upper in _PROXY_NAMES:
            _validate_proxy(value)
        elif upper == _NO_PROXY_NAME:
            _validate_no_proxy(value)
        result[name] = value
    return result
