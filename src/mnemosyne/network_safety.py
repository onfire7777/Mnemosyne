"""Fail-closed URL validation and fetch helpers for operator-configured endpoints."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ValidatedFetchUrl:
    url: str
    scheme: str
    host: str
    port: int
    origin: str
    resolved_addresses: tuple[str, ...]
    pinned_address: str


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so a validated URL cannot pivot to a new origin."""

    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, pinned_address: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pinned_address = pinned_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, pinned_address: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pinned_address = pinned_address

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, validated: ValidatedFetchUrl) -> None:
        super().__init__()
        self._validated = validated

    def http_open(self, req):  # type: ignore[no-untyped-def]
        def connection_factory(
            host: str,
            timeout: object = socket._GLOBAL_DEFAULT_TIMEOUT,
            **kwargs: Any,
        ):
            return _PinnedHTTPConnection(
                host,
                timeout=timeout,
                pinned_address=self._validated.pinned_address,
                **kwargs,
            )

        return self.do_open(connection_factory, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, validated: ValidatedFetchUrl) -> None:
        super().__init__()
        self._validated = validated

    def https_open(self, req):  # type: ignore[no-untyped-def]
        def connection_factory(
            host: str,
            timeout: object = socket._GLOBAL_DEFAULT_TIMEOUT,
            context: object | None = None,
            **kwargs: Any,
        ):
            if context is None:
                context = self._context
            return _PinnedHTTPSConnection(
                host,
                timeout=timeout,
                context=context,
                pinned_address=self._validated.pinned_address,
                **kwargs,
            )

        return self.do_open(connection_factory, req, context=self._context)


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_fetch_url(
    url: str,
    *,
    allow_insecure_localhost: bool,
    purpose: str,
) -> ValidatedFetchUrl:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{purpose} must be http(s) with a hostname")
    if parsed.username or parsed.password:
        raise ValueError(f"{purpose} must not contain userinfo credentials")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{purpose} port is invalid") from exc
    if parsed.scheme != "https" and not (
        allow_insecure_localhost and is_loopback_host(parsed.hostname)
    ):
        raise ValueError(
            f"{purpose} requires https unless insecure localhost is explicitly allowed"
        )
    allow_loopback = (
        parsed.scheme != "https"
        and allow_insecure_localhost
        and is_loopback_host(parsed.hostname)
    )
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    addresses = _resolve_allowed_addresses(
        parsed.hostname,
        port=port,
        allow_loopback=allow_loopback,
        purpose=purpose,
    )
    return ValidatedFetchUrl(
        url=url,
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=port,
        origin=_origin(parsed.scheme, parsed.hostname, explicit_port),
        resolved_addresses=addresses,
        pinned_address=addresses[0],
    )


def safe_urlopen(
    request: urllib.request.Request | str,
    *,
    validated: ValidatedFetchUrl,
    timeout: float,
):
    _validate_request_matches(request, validated)
    opener = urllib.request.build_opener(
        NoRedirectHandler(),
        _PinnedHTTPHandler(validated),
        _PinnedHTTPSHandler(validated),
    )
    return opener.open(request, timeout=timeout)


def _resolve_allowed_addresses(
    host: str,
    *,
    port: int,
    allow_loopback: bool,
    purpose: str,
) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"{purpose} hostname could not be resolved: {host}") from exc
    resolved: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        address = str(sockaddr[0])
        if address not in resolved:
            resolved.append(address)
    if not resolved:
        raise ValueError(f"{purpose} hostname resolved to no addresses: {host}")
    for address in resolved:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError(f"{purpose} hostname resolved to invalid address: {address}") from exc
        if allow_loopback and ip.is_loopback:
            continue
        if not ip.is_global:
            raise ValueError(
                f"{purpose} hostname must not resolve to private, loopback, link-local, reserved, or metadata addresses"
            )
    return tuple(resolved)


def _origin(scheme: str, host: str, explicit_port: int | None) -> str:
    origin_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    origin_port = "" if explicit_port is None else f":{explicit_port}"
    return f"{scheme}://{origin_host}{origin_port}"


def _validate_request_matches(
    request: urllib.request.Request | str,
    validated: ValidatedFetchUrl,
) -> None:
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if (
        parsed.scheme != validated.scheme
        or parsed.hostname != validated.host
        or port != validated.port
    ):
        raise ValueError("request URL no longer matches the validated fetch URL")
