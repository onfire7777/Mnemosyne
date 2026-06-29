"""OIDC JWKS loading helpers shared by CLI and hosted MCP exchange."""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mnemosyne.network_safety import safe_urlopen, validate_fetch_url
from mnemosyne.security import OidcAuthorizationPolicy, SessionAuthError


def load_oidc_jwks(
    *,
    jwks: str | None,
    jwks_file: str | None,
    jwks_url: str | None,
    allow_insecure_url: bool,
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    max_bytes = int(max_bytes)
    if max_bytes <= 0:
        raise SessionAuthError("OIDC JWKS max bytes must be positive")
    sources = [bool(jwks), bool(jwks_file), bool(jwks_url)]
    if sum(sources) != 1:
        raise SessionAuthError("OIDC session exchange requires exactly one JWKS source")
    if jwks:
        raw = jwks
    elif jwks_file:
        raw = _decode_jwks_bytes(_read_file_bytes(Path(jwks_file).expanduser(), max_bytes))
    else:
        assert jwks_url is not None
        raw = _decode_jwks_bytes(
            _read_url_bytes(
                jwks_url,
                allow_insecure_url=allow_insecure_url,
                timeout=timeout,
                max_bytes=max_bytes,
            )
        )
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SessionAuthError("OIDC JWKS is not valid JSON") from exc
    if not isinstance(loaded, dict):
        raise SessionAuthError("OIDC JWKS must be a JSON object")
    return loaded


def oidc_jwks_loader(
    *,
    jwks: str | None,
    jwks_file: str | None,
    jwks_url: str | None,
    allow_insecure_url: bool,
    timeout: float,
    max_bytes: int,
) -> Callable[[], dict[str, Any]] | None:
    if jwks_file or jwks_url:
        return lambda: load_oidc_jwks(
            jwks=jwks,
            jwks_file=jwks_file,
            jwks_url=jwks_url,
            allow_insecure_url=allow_insecure_url,
            timeout=timeout,
            max_bytes=max_bytes,
        )
    return None


def load_oidc_authorization_policy(
    *,
    policy: str | None,
    policy_file: str | None,
) -> OidcAuthorizationPolicy | None:
    sources = [bool(policy), bool(policy_file)]
    if sum(sources) > 1:
        raise SessionAuthError("OIDC authz policy requires at most one source")
    if not any(sources):
        return None
    raw = policy if policy else Path(str(policy_file)).expanduser().read_text(encoding="utf-8")
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SessionAuthError("OIDC authz policy is not valid JSON") from exc
    if not isinstance(loaded, dict):
        raise SessionAuthError("OIDC authz policy must be a JSON object")
    return OidcAuthorizationPolicy.from_mapping(loaded)


def _read_file_bytes(path: Path, max_bytes: int) -> bytes:
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise SessionAuthError("OIDC JWKS exceeds configured size limit")
    return data


def _read_url_bytes(url: str, *, allow_insecure_url: bool, timeout: float, max_bytes: int) -> bytes:
    try:
        validated_url = validate_fetch_url(
            url,
            allow_insecure_localhost=allow_insecure_url,
            purpose="OIDC JWKS URL",
        )
    except ValueError as exc:
        message = str(exc)
        if "requires https unless insecure localhost is explicitly allowed" in message:
            message = "OIDC JWKS URL must use https unless insecure URLs are explicitly allowed"
        raise SessionAuthError(message) from exc
    try:
        with safe_urlopen(url, validated=validated_url, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise SessionAuthError("OIDC JWKS URL could not be loaded") from exc
    if len(data) > max_bytes:
        raise SessionAuthError("OIDC JWKS exceeds configured size limit")
    return data


def _decode_jwks_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SessionAuthError("OIDC JWKS is not valid UTF-8") from exc
