"""Pure endpoint validation; no network calls are made by production policy."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlsplit

from .errors import FailureClass, ProviderError, failure


Resolver = Callable[[str, int, int, int], Iterable[tuple[int, int, int, str, tuple[object, ...]]]]


@dataclass(frozen=True)
class ValidatedEndpoint:
    url: str
    scheme: str
    host: str
    connect_host: str
    port: int
    path: str
    loopback_only: bool


def _split(url: str):
    if not isinstance(url, str) or not url or any(ord(char) < 0x20 for char in url) or len(url.encode("utf-8", "replace")) > 2_048:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint text is invalid or oversized"))
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint port is malformed")) from None
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint authority is missing or contains user-info"))
    if parsed.fragment or parsed.query:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint contains a fragment or query"))
    if parsed.hostname is None or not parsed.hostname or any(char.isspace() for char in parsed.hostname):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint hostname is invalid"))
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    if not 1 <= port <= 65535:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint port is outside range"))
    if parsed.path == "" or not parsed.path.startswith("/"):
        path = "/"
    else:
        path = parsed.path
    return parsed, parsed.hostname, port, path


def validate_production_endpoint(url: str, *, verify_tls: bool = True) -> ValidatedEndpoint:
    parsed, host, port, path = _split(url)
    if parsed.scheme.lower() != "https":
        raise ProviderError(failure(FailureClass.INSECURE_SCHEME, "production provider endpoints require HTTPS"))
    if verify_tls is not True:
        raise ProviderError(failure(FailureClass.TLS_VERIFICATION_FAILURE, "certificate and hostname verification may not be disabled"))
    # No DNS resolution is performed here. A future live adapter must resolve
    # and verify the destination immediately before a TLS connection.
    return ValidatedEndpoint(url, "https", host, host, port, path, False)


def _is_loopback_address(value: object) -> bool:
    try:
        return ipaddress.ip_address(str(value)).is_loopback
    except ValueError:
        return False


def _resolved_addresses(host: str, port: int, resolver: Resolver) -> list[tuple[int, str]]:
    try:
        records = list(resolver(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM))
    except (OSError, ValueError):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake endpoint resolution failed")) from None
    addresses: list[tuple[int, str]] = []
    for family, _socktype, _proto, _canonname, sockaddr in records:
        if family == socket.AF_INET:
            addresses.append((family, str(sockaddr[0])))
        elif family == socket.AF_INET6:
            addresses.append((family, str(sockaddr[0])))
        else:
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake endpoint has an unsupported address family"))
    if not addresses or any(not _is_loopback_address(address) for _family, address in addresses):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake endpoint does not resolve exclusively to loopback"))
    return addresses


def validate_fake_loopback_endpoint(
    url: str,
    *,
    allow_loopback_http: bool,
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedEndpoint:
    if allow_loopback_http is not True:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "loopback HTTP requires explicit test-only opt-in"))
    parsed, host, port, path = _split(url)
    if parsed.scheme.lower() != "http":
        raise ProviderError(failure(FailureClass.INSECURE_SCHEME, "fake provider must use explicit loopback HTTP"))
    if host in {"0.0.0.0", "::", "[::]", ""}:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "wildcard fake-provider destination is forbidden"))
    try:
        host_is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        host_is_loopback = host.lower() == "localhost"
    if not host_is_loopback:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake endpoint hostname is not explicit loopback"))
    addresses = _resolved_addresses(host, port, resolver)
    family, connect_host = addresses[0]
    del family
    return ValidatedEndpoint(url, "http", host, connect_host, port, path, True)


def validate_fake_bind_host(host: str) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake provider must bind to explicit loopback"))


def redirect_rejection(location: str | None = None):
    detail = "redirects are disabled"
    if location:
        detail += " (location withheld)"
    return failure(FailureClass.REDIRECT_REJECTED, detail)
