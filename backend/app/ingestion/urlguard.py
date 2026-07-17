"""Target URL validation: first line of defence against SSRF and junk input.

The API route runs this in syntactic-only mode (no DNS); the worker re-runs it
with a real resolver right before fetching. Network-level protections are added
at deployment (Phase 3).
"""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

Resolver = Callable[[str], list[str]]

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    pass


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def _check_ip(ip_text: str, context: str) -> None:
    ip = ipaddress.ip_address(ip_text)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise UnsafeURLError(f"{context} address {ip} is not publicly routable")


def validate_target_url(
    url: str,
    *,
    resolve: Resolver | None = None,
    deny_hosts: frozenset[str] | set[str] = frozenset(),
) -> str:
    if not url or not url.strip():
        raise UnsafeURLError("URL is empty")
    parts = urlsplit(url.strip())

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        scheme = parts.scheme or "(none)"
        raise UnsafeURLError(f"scheme {scheme!r} is not allowed; use http or https")

    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise UnsafeURLError("localhost is not a valid scrape target")

    deny = {h.lower() for h in deny_hosts}
    if host.lower() in deny:
        raise UnsafeURLError(f"{host} is on the operator denylist")

    try:
        _check_ip(host, "target")
        is_ip_literal = True
    except ValueError as exc:
        if isinstance(exc, UnsafeURLError):
            raise
        is_ip_literal = False  # a hostname, not an IP literal

    if not is_ip_literal and resolve is not None:
        try:
            addresses = resolve(host)
        except OSError as exc:
            raise UnsafeURLError(f"DNS resolution failed for {host}: {exc}") from exc
        if not addresses:
            raise UnsafeURLError(f"DNS returned no addresses for {host}")
        for address in addresses:
            _check_ip(address, f"{host} resolved")
            if address in deny:
                raise UnsafeURLError(f"{host} resolves to a denylisted address")

    return urlunsplit(parts)
