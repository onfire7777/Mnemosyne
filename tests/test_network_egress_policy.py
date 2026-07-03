from __future__ import annotations

import re
import socket
import ssl
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from mnemosyne.network_safety import ValidatedFetchUrl, safe_urlopen, validate_fetch_url


ROOT = Path(__file__).resolve().parents[1]

RAW_EGRESS_PATTERNS = {
    "urllib.request.urlopen": re.compile(r"\burllib\.request\.urlopen\s*\("),
    "requests.request": re.compile(
        r"\brequests\.(?:get|post|put|patch|delete|head|options|request)\s*\("
    ),
    "httpx.AsyncClient": re.compile(r"\bhttpx\.AsyncClient\s*\("),
    "httpx.Client": re.compile(r"\bhttpx\.Client\s*\("),
    "aiohttp.ClientSession": re.compile(r"\baiohttp\.ClientSession\s*\("),
}

RAW_EGRESS_SCAN_ROOTS = ("src", "infra", "services")
RAW_EGRESS_SUFFIXES = (".py", ".sh", ".yml", ".yaml", "Dockerfile")
ALLOWED_RAW_EGRESS = {
    (
        "src/mnemosyne/cli.py",
        "httpx.AsyncClient",
    ): "official MCP SDK transport after cmd_mcp_streamable_http_soak validates the URL",
    (
        "services/embedding/Dockerfile",
        "urllib.request.urlopen",
    ): "container-local healthcheck against 127.0.0.1",
}


def test_safe_urlopen_accepts_custom_tls_context(monkeypatch) -> None:
    context = ssl.create_default_context()
    opened: dict[str, Any] = {}
    captured_handlers: tuple[Any, ...] = ()
    response = object()

    class FakeOpener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> object:
            opened["request"] = request
            opened["timeout"] = timeout
            return response

    def fake_build_opener(*handlers: Any) -> FakeOpener:
        nonlocal captured_handlers
        captured_handlers = handlers
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    request = urllib.request.Request("https://example.com/v1/secret")
    validated = ValidatedFetchUrl(
        url="https://example.com/v1/secret",
        scheme="https",
        host="example.com",
        port=443,
        origin="https://example.com",
        resolved_addresses=("93.184.216.34",),
        pinned_address="93.184.216.34",
    )

    result = safe_urlopen(request, validated=validated, timeout=7.5, context=context)

    assert result is response
    assert opened == {"request": request, "timeout": 7.5}
    https_handlers = [
        handler for handler in captured_handlers if handler.__class__.__name__ == "_PinnedHTTPSHandler"
    ]
    assert len(https_handlers) == 1
    assert https_handlers[0]._context is context


def test_internal_private_addresses_require_explicit_host_allowlist(monkeypatch) -> None:
    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.20.0.12", 8200))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="must not resolve to private"):
        validate_fetch_url(
            "https://vault.mnemo.local:8200/v1/secret",
            allow_insecure_localhost=True,
            purpose="Vault URL",
        )

    validated = validate_fetch_url(
        "https://vault.mnemo.local:8200/v1/secret",
        allow_insecure_localhost=True,
        allow_internal_hosts=("vault.mnemo.local",),
        purpose="Vault URL",
    )
    assert validated.pinned_address == "172.20.0.12"


def test_internal_http_hosts_require_explicit_insecure_allowlist(monkeypatch) -> None:
    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.20.0.13", 11434))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="requires https unless insecure localhost"):
        validate_fetch_url(
            "http://ollama.mnemo.local:11434/api/chat",
            allow_insecure_localhost=True,
            purpose="Ollama URL",
        )

    validated = validate_fetch_url(
        "http://ollama.mnemo.local:11434/api/chat",
        allow_insecure_localhost=True,
        allow_insecure_internal_hosts=("ollama.mnemo.local",),
        purpose="Ollama URL",
    )
    assert validated.pinned_address == "172.20.0.13"


def test_raw_outbound_http_calls_are_policy_gated() -> None:
    observed: set[tuple[str, str]] = set()
    for root_name in RAW_EGRESS_SCAN_ROOTS:
        for path in (ROOT / root_name).rglob("*"):
            if not path.is_file() or not _is_scanned_source(path):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel == "src/mnemosyne/network_safety.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name, pattern in RAW_EGRESS_PATTERNS.items():
                if pattern.search(text):
                    observed.add((rel, name))

    assert observed == set(ALLOWED_RAW_EGRESS), "\n".join(
        [
            "raw outbound HTTP clients must route through mnemosyne.network_safety.safe_urlopen",
            "or be listed in ALLOWED_RAW_EGRESS with a boundary-specific reason.",
            f"unexpected={sorted(observed - set(ALLOWED_RAW_EGRESS))}",
            f"stale_allowlist={sorted(set(ALLOWED_RAW_EGRESS) - observed)}",
        ]
    )


def _is_scanned_source(path: Path) -> bool:
    return path.name == "Dockerfile" or path.suffix in RAW_EGRESS_SUFFIXES
