"""Fail-closed URL validation and fetch helpers for operator-configured endpoints."""

from __future__ import annotations

import http.client
import io
import ipaddress
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

_DEFAULT_SSL_CONTEXT_LOCK = threading.Lock()
_DEFAULT_SSL_CONTEXT_CACHE: dict[tuple[str | None, str | None], ssl.SSLContext] = {}

_STDLIB_GETADDRINFO = socket.getaddrinfo
_STDLIB_BUILD_OPENER = urllib.request.build_opener

_DNS_CACHE_TTL_SECONDS = 60.0
_DNS_CACHE_MAX_ENTRIES = 256
_DNS_CACHE_LOCK = threading.Lock()
_DNS_CACHE: dict[tuple[str, int, bool, bool, bool], tuple[float, tuple[str, ...]]] = {}

_POOL_MAX_PER_ORIGIN = 8
_POOL_MAX_ORIGINS = 64
_POOL_IDLE_TTL_SECONDS = 60.0


def _ssl_env_key() -> tuple[str | None, str | None]:
    return (os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR"))


def _default_ssl_context() -> ssl.SSLContext:
    env_key = _ssl_env_key()
    cached = _DEFAULT_SSL_CONTEXT_CACHE.get(env_key)
    if cached is not None:
        return cached
    with _DEFAULT_SSL_CONTEXT_LOCK:
        cached = _DEFAULT_SSL_CONTEXT_CACHE.get(env_key)
        if cached is None:
            if len(_DEFAULT_SSL_CONTEXT_CACHE) >= 16:
                _DEFAULT_SSL_CONTEXT_CACHE.clear()
            cached = ssl.create_default_context()
            _DEFAULT_SSL_CONTEXT_CACHE[env_key] = cached
    return cached


@dataclass(frozen=True)
class ValidatedFetchUrl:
    url: str
    scheme: str
    host: str
    port: int
    origin: str
    resolved_addresses: tuple[str, ...]
    pinned_address: str
    # Discovery's local-only policy must survive into the request opener.
    loopback_only: bool = False


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
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
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
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _PooledHTTPResponse:
    """Context-manager response backed by buffered bytes from a keep-alive connection."""

    def __init__(
        self,
        *,
        url: str,
        status: int,
        reason: str,
        headers: http.client.HTTPMessage,
        body: bytes,
    ) -> None:
        self.url = url
        self.status = int(status)
        self.code = int(status)
        self.reason = reason
        self.headers = headers
        self.msg = headers
        self._stream = io.BytesIO(body)

    def read(self, amt: int | None = None) -> bytes:
        return self._stream.read() if amt is None else self._stream.read(amt)

    def readline(self, limit: int = -1) -> bytes:
        return self._stream.readline(limit)

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def info(self) -> http.client.HTTPMessage:
        return self.headers

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> _PooledHTTPResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _PooledStreamResponse:
    """Streaming wrapper for SSE responses; closes its pinned connection on exit."""

    def __init__(
        self,
        *,
        url: str,
        response: http.client.HTTPResponse,
        conn: http.client.HTTPConnection,
    ) -> None:
        self.url = url
        self._response = response
        self._conn = conn
        self.status = int(response.status)
        self.code = int(response.status)
        self.reason = response.reason
        self.headers = response.msg
        self.msg = response.msg

    def read(self, amt: int | None = None) -> bytes:
        return self._response.read() if amt is None else self._response.read(amt)

    def readline(self, limit: int = -1) -> bytes:
        return self._response.readline(limit)

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def info(self) -> http.client.HTTPMessage:
        return self.headers

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._conn.close()

    def __enter__(self) -> _PooledStreamResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


_PoolKey = tuple[str, str, int, str, int, bool]


class _PinnedConnectionPool:
    """Thread-safe keep-alive connection pool bound to pinned validated IP addresses."""

    def __init__(
        self,
        *,
        max_per_origin: int = _POOL_MAX_PER_ORIGIN,
        max_origins: int = _POOL_MAX_ORIGINS,
        idle_ttl_seconds: float = _POOL_IDLE_TTL_SECONDS,
    ) -> None:
        self._max_per_origin = max_per_origin
        self._max_origins = max_origins
        self._idle_ttl_seconds = idle_ttl_seconds
        self._lock = threading.Lock()
        self._buckets: dict[
            _PoolKey, deque[tuple[http.client.HTTPConnection, float, ssl.SSLContext | None]]
        ] = {}

    def acquire(
        self,
        validated: ValidatedFetchUrl,
        *,
        timeout: float,
        https_context: ssl.SSLContext | None,
    ) -> tuple[_PoolKey, http.client.HTTPConnection, bool]:
        ctx = https_context if validated.scheme == "https" else None
        key: _PoolKey = (
            validated.scheme,
            validated.host,
            validated.port,
            validated.pinned_address,
            id(ctx) if ctx is not None else 0,
            validated.loopback_only,
        )
        now = time.monotonic()
        stale: list[http.client.HTTPConnection] = []
        chosen: http.client.HTTPConnection | None = None
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket:
                while bucket:
                    conn, last_used, conn_ctx = bucket.pop()
                    if (
                        conn.sock is None
                        or now - last_used > self._idle_ttl_seconds
                        or conn_ctx is not ctx
                    ):
                        stale.append(conn)
                        continue
                    chosen = conn
                    break
                if not bucket:
                    self._buckets.pop(key, None)
        for conn in stale:
            try:
                conn.close()
            except OSError:
                pass
        if chosen is not None:
            chosen.timeout = timeout
            try:
                if chosen.sock is not None:
                    chosen.sock.settimeout(timeout)
            except OSError:
                try:
                    chosen.close()
                except OSError:
                    pass
                chosen = None
        if chosen is not None:
            return key, chosen, True
        return key, self._new_connection(validated, timeout=timeout, https_context=ctx), False

    @staticmethod
    def _new_connection(
        validated: ValidatedFetchUrl,
        *,
        timeout: float,
        https_context: ssl.SSLContext | None,
    ) -> http.client.HTTPConnection:
        if validated.scheme == "https":
            return _PinnedHTTPSConnection(
                validated.host,
                port=validated.port,
                timeout=timeout,
                context=https_context,
                pinned_address=validated.pinned_address,
            )
        return _PinnedHTTPConnection(
            validated.host,
            port=validated.port,
            timeout=timeout,
            pinned_address=validated.pinned_address,
        )

    def release(
        self,
        key: _PoolKey,
        conn: http.client.HTTPConnection,
        https_context: ssl.SSLContext | None,
    ) -> None:
        if conn.sock is None:
            try:
                conn.close()
            except OSError:
                pass
            return
        ctx = https_context if key[0] == "https" else None
        evicted: list[http.client.HTTPConnection] = []
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_origins:
                    oldest_key = next(iter(self._buckets))
                    old_bucket = self._buckets.pop(oldest_key)
                    evicted.extend(item[0] for item in old_bucket)
                bucket = deque()
                self._buckets[key] = bucket
            while len(bucket) >= self._max_per_origin:
                old_conn, _, _ = bucket.popleft()
                evicted.append(old_conn)
            bucket.append((conn, time.monotonic(), ctx))
        for old_conn in evicted:
            try:
                old_conn.close()
            except OSError:
                pass

    def clear(self) -> None:
        to_close: list[http.client.HTTPConnection] = []
        with self._lock:
            for bucket in self._buckets.values():
                to_close.extend(item[0] for item in bucket)
            self._buckets.clear()
        for conn in to_close:
            try:
                conn.close()
            except OSError:
                pass


_PINNED_CONNECTION_POOL = _PinnedConnectionPool()


def clear_network_caches() -> None:
    """Clear the validated-IP DNS cache and close idle pooled connections."""
    with _DNS_CACHE_LOCK:
        _DNS_CACHE.clear()
    _PINNED_CONNECTION_POOL.clear()


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
    def __init__(self, validated: ValidatedFetchUrl, context: ssl.SSLContext | None = None) -> None:
        super().__init__(context=context)
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
    allow_internal_hosts: Iterable[str] = (),
    allow_insecure_internal_hosts: Iterable[str] = (),
    loopback_only: bool = False,
) -> ValidatedFetchUrl:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{purpose} must be http(s) with a hostname")
    if parsed.username or parsed.password:
        raise ValueError(f"{purpose} must not contain userinfo credentials")
    if loopback_only and not is_loopback_host(parsed.hostname):
        raise ValueError(f"{purpose} must use a loopback hostname")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{purpose} port is invalid") from exc
    normalized_host = _normalize_host(parsed.hostname)
    internal_hosts = _normalized_hosts(allow_internal_hosts)
    insecure_internal_hosts = _normalized_hosts(allow_insecure_internal_hosts)
    allow_insecure_internal = (
        parsed.scheme != "https" and normalized_host in insecure_internal_hosts
    )
    if parsed.scheme != "https" and not (
        allow_insecure_localhost and is_loopback_host(parsed.hostname)
    ) and not allow_insecure_internal:
        raise ValueError(
            f"{purpose} requires https unless insecure localhost is explicitly allowed "
            "or the host is on the internal HTTP allowlist"
        )
    allow_loopback = (
        (loopback_only or (parsed.scheme != "https" and allow_insecure_localhost))
        and is_loopback_host(parsed.hostname)
    )
    allow_internal = normalized_host in internal_hosts or allow_insecure_internal
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    addresses = _resolve_allowed_addresses(
        parsed.hostname,
        port=port,
        allow_loopback=allow_loopback,
        allow_internal=allow_internal,
        purpose=purpose,
        loopback_only=loopback_only,
    )
    return ValidatedFetchUrl(
        url=url,
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=port,
        origin=_origin(parsed.scheme, parsed.hostname, explicit_port),
        resolved_addresses=addresses,
        pinned_address=addresses[0],
        loopback_only=loopback_only,
    )


def _proxy_configured_for(scheme: str) -> bool:
    proxies = urllib.request.getproxies()
    return bool(proxies.get(scheme) or proxies.get("all"))


def _pooled_urlopen(
    request: urllib.request.Request | str,
    *,
    validated: ValidatedFetchUrl,
    timeout: float,
    https_context: ssl.SSLContext | None,
):
    if isinstance(request, urllib.request.Request):
        url = request.full_url
        method = request.get_method()
        raw_headers = dict(request.header_items())
        body_data = request.data
    else:
        url = str(request)
        method = "GET"
        raw_headers = {}
        body_data = None

    if body_data is not None and not isinstance(body_data, (bytes, bytearray, memoryview)):
        return None  # Caller passed an iterable/stream body; let urllib handle it.

    body_bytes: bytes | None = bytes(body_data) if body_data is not None else None
    parsed = urlsplit(url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    headers = dict(raw_headers)
    lower_keys = {key.lower() for key in headers}
    if "connection" not in lower_keys:
        headers["Connection"] = "keep-alive"
    if body_bytes is not None and "content-length" not in lower_keys:
        headers["Content-Length"] = str(len(body_bytes))
    if "user-agent" not in lower_keys:
        headers["User-Agent"] = "Python-urllib/3"

    wants_sse = "text/event-stream" in str(
        next((v for k, v in headers.items() if k.lower() == "accept"), "")
    ).lower()

    for attempt in range(2):
        key, conn, reused = _PINNED_CONNECTION_POOL.acquire(
            validated,
            timeout=timeout,
            https_context=https_context,
        )
        try:
            conn.request(method, target, body=body_bytes, headers=headers)
            resp = conn.getresponse()
        except (
            http.client.RemoteDisconnected,
            http.client.BadStatusLine,
            http.client.CannotSendRequest,
            http.client.ResponseNotReady,
            ConnectionResetError,
            BrokenPipeError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            try:
                conn.close()
            except OSError:
                pass
            if reused and attempt == 0:
                continue
            raise urllib.error.URLError(exc) from exc

        resp_content_type = str(resp.getheader("Content-Type") or "").lower()
        is_sse = wants_sse or "text/event-stream" in resp_content_type
        if 200 <= resp.status < 300 and is_sse:
            return _PooledStreamResponse(url=url, response=resp, conn=conn)

        try:
            payload = resp.read()
        except (OSError, http.client.HTTPException) as exc:
            try:
                conn.close()
            except OSError:
                pass
            raise urllib.error.URLError(exc) from exc

        if not resp.will_close and conn.sock is not None:
            _PINNED_CONNECTION_POOL.release(key, conn, https_context)
        else:
            try:
                conn.close()
            except OSError:
                pass

        # Fail-closed NoRedirect (3xx) and HTTP error (4xx/5xx) semantics.
        if resp.status >= 300:
            raise urllib.error.HTTPError(
                url,
                resp.status,
                resp.reason,
                resp.msg,
                io.BytesIO(payload),
            )
        return _PooledHTTPResponse(
            url=url,
            status=resp.status,
            reason=resp.reason,
            headers=resp.msg,
            body=payload,
        )

    raise urllib.error.URLError("pooled connection exhausted retries")


def safe_urlopen(
    request: urllib.request.Request | str,
    *,
    validated: ValidatedFetchUrl,
    timeout: float,
    context: ssl.SSLContext | None = None,
):
    _validate_request_matches(request, validated)
    https_context = context if context is not None else _default_ssl_context()
    use_pool = (
        urllib.request.build_opener is _STDLIB_BUILD_OPENER
        and (validated.loopback_only or not _proxy_configured_for(validated.scheme))
    )
    if use_pool:
        pooled = _pooled_urlopen(
            request,
            validated=validated,
            timeout=timeout,
            https_context=https_context,
        )
        if pooled is not None:
            return pooled
    # Fallback opener preserves monkeypatched build_opener hooks, streaming
    # request bodies, and explicit non-loopback environment HTTP proxies.
    proxy_handlers = [urllib.request.ProxyHandler({})] if validated.loopback_only else []
    opener = urllib.request.build_opener(
        *proxy_handlers,
        NoRedirectHandler(),
        _PinnedHTTPHandler(validated),
        _PinnedHTTPSHandler(validated, context=https_context),
    )
    return opener.open(request, timeout=timeout)


def _resolve_allowed_addresses(
    host: str,
    *,
    port: int,
    allow_loopback: bool,
    allow_internal: bool,
    purpose: str,
    loopback_only: bool = False,
) -> tuple[str, ...]:
    normalized_host = _normalize_host(host)
    can_cache = (
        socket.getaddrinfo is _STDLIB_GETADDRINFO
        and not loopback_only
        and not is_loopback_host(host)
    )
    cache_key = (normalized_host, int(port), bool(allow_loopback), bool(allow_internal), bool(loopback_only))
    if can_cache:
        now = time.monotonic()
        with _DNS_CACHE_LOCK:
            cached = _DNS_CACHE.get(cache_key)
            if cached is not None and now - cached[0] <= _DNS_CACHE_TTL_SECONDS:
                return cached[1]
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
        if loopback_only and not ip.is_loopback:
            raise ValueError(f"{purpose} hostname must resolve only to loopback addresses")
        if allow_loopback and ip.is_loopback:
            continue
        if allow_internal and _is_allowed_internal_address(ip):
            continue
        if not ip.is_global:
            raise ValueError(
                f"{purpose} hostname must not resolve to private, loopback, link-local, reserved, or metadata addresses"
            )
    result = tuple(resolved)
    if can_cache:
        now = time.monotonic()
        with _DNS_CACHE_LOCK:
            if len(_DNS_CACHE) >= _DNS_CACHE_MAX_ENTRIES:
                expired = [k for k, (ts, _) in _DNS_CACHE.items() if now - ts > _DNS_CACHE_TTL_SECONDS]
                for k in expired:
                    _DNS_CACHE.pop(k, None)
                if len(_DNS_CACHE) >= _DNS_CACHE_MAX_ENTRIES:
                    _DNS_CACHE.pop(next(iter(_DNS_CACHE)))
            _DNS_CACHE[cache_key] = (now, result)
    return result


def _is_allowed_internal_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return bool(ip.is_private or ip.is_loopback)


def _normalized_hosts(hosts: Iterable[str]) -> frozenset[str]:
    return frozenset(filter(None, (_normalize_host(host) for host in hosts)))


def _normalize_host(host: str) -> str:
    return host.strip().lower().strip("[]")


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
