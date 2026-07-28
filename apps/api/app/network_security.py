"""Security policy for user-supplied remote media URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class RemoteUrlPolicyError(ValueError):
    pass


def validate_remote_url(url: str, *, resolve: bool) -> str:
    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RemoteUrlPolicyError("invalid remote URL") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise RemoteUrlPolicyError("only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname:
        raise RemoteUrlPolicyError("remote URL requires a host")
    if parsed.username is not None or parsed.password is not None:
        raise RemoteUrlPolicyError("credentials in remote URLs are not allowed")
    if port is not None and not 1 <= port <= 65535:
        raise RemoteUrlPolicyError("invalid remote URL port")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise RemoteUrlPolicyError("local network targets are not allowed")

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        addresses.add(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        if resolve:
            try:
                for result in socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM):
                    addresses.add(ipaddress.ip_address(result[4][0].split("%", 1)[0]))
            except (OSError, ValueError) as exc:
                raise RemoteUrlPolicyError("remote host could not be resolved safely") from exc

    if addresses and any(not address.is_global for address in addresses):
        raise RemoteUrlPolicyError("local or non-public network targets are not allowed")
    return value
