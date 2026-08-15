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
    if not isinstance(url, str) or not url or any(ord(char) < 0x20 for char in url):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint text is invalid or oversized"))
    try:
        if len(url.encode("utf-8")) > 2_048:
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint text is invalid or oversized"))
    except UnicodeEncodeError:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint text is invalid or oversized")) from None
    try:
        parsed = urlsplit(url)
        port = parsed.port
        hostname = parsed.hostname
    except (TypeError, ValueError):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint port is malformed")) from None
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint authority is missing or contains user-info"))
    if parsed.fragment or parsed.query:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint contains a fragment or query"))
    if hostname is None or not hostname or any(char.isspace() for char in hostname):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint hostname is invalid"))
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    if not 1 <= port <= 65535:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint port is outside range"))
    if parsed.path == "":
        path = "/"
    elif not parsed.path.startswith("/") or any(ord(char) < 0x20 for char in parsed.path):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint request path is invalid"))
    else:
        path = parsed.path
    try:
        if len(path.encode("utf-8")) > 2_048:
            raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint request path is oversized"))
    except UnicodeEncodeError:
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "endpoint request path is invalid")) from None
    return parsed, hostname, port, path


def validate_production_endpoint(url: str, *, verify_tls: bool = True) -> ValidatedEndpoint:
    parsed, host, port, path = _split(url)
    if parsed.scheme.lower() != "https":
        raise ProviderError(failure(FailureClass.INSECURE_SCHEME, "production provider endpoints require HTTPS"))
    if verify_tls is not True:
        raise ProviderError(failure(FailureClass.TLS_VERIFICATION_FAILURE, "certificate and hostname verification may not be disabled"))
    # No DNS resolution is performed here. A future live adapter must resolve
    # and verify the destination immediately before a TLS connection.
    return ValidatedEndpoint(url, "https", host, host, port, path, False)


def resolve_production_transport_endpoint(
    endpoint: ValidatedEndpoint,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedEndpoint:
    """Re-resolve a production authority immediately before TLS connect.

    This is deliberately adjacent to, rather than a replacement for, the
    pure configuration-time policy.  It prevents a hostname from becoming a
    loopback/private destination between validation and socket creation while
    retaining the hostname for TLS SNI and certificate verification.
    """
    try:
        checked = validate_production_endpoint(endpoint.url, verify_tls=True)
        if (
            endpoint != checked or endpoint.connect_host != endpoint.host
            or endpoint.loopback_only is not False
        ):
            raise ValueError
        records = list(resolver(checked.host, checked.port, socket.AF_UNSPEC, socket.SOCK_STREAM))
    except ProviderError:
        raise
    except (OSError, ValueError, TypeError):
        raise ProviderError(failure(FailureClass.DNS_OR_CONNECTION_FAILURE, "production endpoint resolution failed")) from None
    addresses: list[str] = []
    try:
        for family, _socktype, _proto, _canonname, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                raise ValueError
            address = ipaddress.ip_address(str(sockaddr[0]))
            # A provider address must be globally routable.  Reject an answer
            # set if *any* record is local so selection cannot be gamed.
            if not address.is_global:
                raise ValueError
            addresses.append(str(address))
    except (IndexError, ValueError, TypeError):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "production endpoint destination is disallowed")) from None
    if not addresses:
        raise ProviderError(failure(FailureClass.DNS_OR_CONNECTION_FAILURE, "production endpoint resolution failed"))
    return ValidatedEndpoint(checked.url, checked.scheme, checked.host, addresses[0], checked.port, checked.path, False)


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
    try:
        for family, _socktype, _proto, _canonname, sockaddr in records:
            if family == socket.AF_INET:
                addresses.append((family, str(sockaddr[0])))
            elif family == socket.AF_INET6:
                addresses.append((family, str(sockaddr[0])))
            else:
                raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake endpoint has an unsupported address family"))
    except ProviderError:
        raise
    except (IndexError, KeyError, TypeError, ValueError):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "fake endpoint resolution failed")) from None
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


def validate_loopback_transport_endpoint(endpoint: ValidatedEndpoint) -> None:
    """Re-check every authority field immediately before a socket is opened.

    This deliberately does not resolve names.  ``connect_host`` must already
    be a numeric loopback address supplied by the endpoint policy.
    """
    try:
        if not isinstance(endpoint, ValidatedEndpoint):
            raise ValueError
        if endpoint.scheme != "http" or endpoint.loopback_only is not True:
            raise ValueError
        if not isinstance(endpoint.connect_host, str) or not endpoint.connect_host:
            raise ValueError
        address = ipaddress.ip_address(endpoint.connect_host)
        if not address.is_loopback or address.is_unspecified or address.is_link_local or address.is_multicast or address.is_reserved:
            raise ValueError
        if isinstance(endpoint.port, bool) or not isinstance(endpoint.port, int) or not 1 <= endpoint.port <= 65535:
            raise ValueError
        if not isinstance(endpoint.path, str) or not endpoint.path or not endpoint.path.startswith("/"):
            raise ValueError
        if any(ord(char) < 0x20 or ord(char) == 0x7f for char in endpoint.path) or len(endpoint.path.encode("utf-8")) > 2_048:
            raise ValueError
        parsed, public_host, public_port, public_path = _split(endpoint.url)
        if parsed.scheme != "http" or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if public_host != endpoint.host or public_port != endpoint.port or public_path != endpoint.path:
            raise ValueError
        # Numeric public authorities must agree with the numeric connection
        # destination.  A validated ``localhost`` URL is allowed, but no other
        # hostname can enter the socket path.
        try:
            public_address = ipaddress.ip_address(public_host)
        except ValueError:
            if public_host.lower() != "localhost":
                raise ValueError
        else:
            if public_address != address:
                raise ValueError
    except (AttributeError, TypeError, UnicodeError, ValueError, OverflowError):
        raise ProviderError(failure(FailureClass.ENDPOINT_POLICY_REJECTION, "transport endpoint authority is invalid")) from None


def redirect_rejection(location: str | None = None):
    detail = "redirects are disabled"
    if location:
        detail += " (location withheld)"
    return failure(FailureClass.REDIRECT_REJECTED, detail)
