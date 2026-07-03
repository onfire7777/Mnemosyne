#!/usr/bin/env python3
"""Vault-transit-backed object-key provider for Mnemosyne.

This is a *real* implementation of Mnemosyne's command-backed object-key
contract (``mnemosyne.storage.CommandKeyManager``). Mnemosyne invokes this
program without a shell, appending the action name as the final argv item and
sending a JSON request on stdin::

    argv:   [...this script..., "<action>"]
    stdin:  {"action": "...", "tenant_id": "...", "cid": "...", "key_id": "..."}

It must emit JSON on stdout:

    get_or_create_key / get_key : {"key": "<urlsafe-base64 32-byte AES key>"}
    has_key                     : {"exists": true|false}
    shred_key                   : {"shredded": true|false}

Real KMS semantics, backed by HashiCorp Vault's transit engine:

* wrap    — a fresh 32-byte data-encryption key (DEK) is generated and
            encrypted ("wrapped") with a **per-object** transit key. Only the
            Vault ciphertext is persisted locally; raw key bytes never rest on
            disk.
* unwrap  — ``get_key`` asks Vault transit to decrypt the stored ciphertext,
            returning the plaintext DEK to Mnemosyne for AES-GCM.
* rotate  — ``rotate`` (extra action, used by the validation harness) advances
            the per-object transit key version; previously wrapped ciphertext
            stays decryptable, new wraps use the new version.
* shred   — ``shred_key`` deletes the per-object transit key in Vault. The
            wrapped DEK can then never be unwrapped again: true crypto-erase.

The mapping ``Mnemosyne key_id -> Vault transit key`` is deterministic, so the
same object always resolves to the same KEK, and the same plaintext DEK is
returned on every ``get_key`` until the key is shredded.

Configuration (environment):

    VAULT_ADDR                       Vault address (default http://localhost:8211)
    VAULT_TOKEN                      Vault token scoped to the transit policy
    MNEMOSYNE_VAULT_TRANSIT_MOUNT    transit mount (default "transit")
    MNEMOSYNE_VAULT_KEY_PREFIX       per-object key prefix (default "mnemosyne-object-")
    MNEMOSYNE_VAULT_WRAP_DIR         dir for wrapped-DEK sidecars
                                     (default infra/vault/out/wrapped-keys)
    MNEMOSYNE_VAULT_TIMEOUT          HTTP timeout seconds (default 15)
    MNEMOSYNE_VAULT_ALLOWED_INTERNAL_HOSTS
                                     comma-separated host allowlist for private
                                     Vault service addresses

No third-party dependencies: uses only the Python standard library so it runs
anywhere Mnemosyne runs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mnemosyne.network_safety import safe_urlopen, validate_fetch_url


class ProviderError(RuntimeError):
    """Raised for any provider-side failure; mapped to a nonzero exit."""


def _vault_addr() -> str:
    return os.environ.get("VAULT_ADDR", "http://localhost:8211").rstrip("/")


def _vault_token() -> str:
    token = os.environ.get("VAULT_TOKEN", "").strip()
    if not token:
        raise ProviderError("VAULT_TOKEN is required")
    return token


def _mount() -> str:
    return os.environ.get("MNEMOSYNE_VAULT_TRANSIT_MOUNT", "transit").strip("/")


def _key_prefix() -> str:
    return os.environ.get("MNEMOSYNE_VAULT_KEY_PREFIX", "mnemosyne-object-")


def _timeout() -> float:
    return float(os.environ.get("MNEMOSYNE_VAULT_TIMEOUT", "15"))


def _allowed_internal_hosts() -> tuple[str, ...]:
    raw = os.environ.get(
        "MNEMOSYNE_VAULT_ALLOWED_INTERNAL_HOSTS",
        "vault.mnemo.local,localhost,127.0.0.1,::1",
    )
    return tuple(host.strip() for host in raw.split(",") if host.strip())


def _wrap_dir() -> Path:
    raw = os.environ.get("MNEMOSYNE_VAULT_WRAP_DIR")
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path(__file__).resolve().parent / "out" / "wrapped-keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _transit_key_name(key_id: str) -> str:
    # key_id is already a 64-hex sha256 from Mnemosyne; keep it deterministic
    # and Vault-name-safe.
    safe = hashlib.sha256(key_id.encode("utf-8")).hexdigest()
    return f"{_key_prefix()}{safe}"


def _wrap_path(key_id: str) -> Path:
    return _wrap_dir() / f"{_transit_key_name(key_id)}.json"


def _vault_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{_vault_addr()}/v1/{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url=url, data=data, method=method)
    req.add_header("X-Vault-Token", _vault_token())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        validated_url = validate_fetch_url(
            url,
            allow_insecure_localhost=True,
            allow_internal_hosts=_allowed_internal_hosts(),
            purpose="Vault transit URL",
        )
        with safe_urlopen(req, validated=validated_url, timeout=_timeout()) as response:
            body = response.read()
    except ValueError as exc:
        raise ProviderError(f"vault {method} {path} rejected: {exc}") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:512]
        raise ProviderError(f"vault {method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"vault {method} {path} unreachable: {exc.reason}") from exc
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"vault {method} {path} returned invalid JSON") from exc


def _ensure_transit_key(name: str) -> None:
    try:
        _vault_request("GET", f"{_mount()}/keys/{name}")
        return
    except ProviderError:
        pass
    _vault_request(
        "POST",
        f"{_mount()}/keys/{name}",
        {"type": "aes256-gcm96", "deletion_allowed": True, "exportable": False},
    )
    # Make sure deletion is allowed (idempotent) so shred can truly erase.
    _vault_request("POST", f"{_mount()}/keys/{name}/config", {"deletion_allowed": True})


def _transit_key_exists(name: str) -> bool:
    try:
        _vault_request("GET", f"{_mount()}/keys/{name}")
        return True
    except ProviderError:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _wrap_dek(name: str, dek: bytes) -> str:
    plaintext = base64.b64encode(dek).decode("ascii")
    resp = _vault_request("POST", f"{_mount()}/encrypt/{name}", {"plaintext": plaintext})
    ciphertext = resp.get("data", {}).get("ciphertext")
    if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:"):
        raise ProviderError("vault encrypt did not return a ciphertext")
    return ciphertext


def _unwrap_dek(name: str, ciphertext: str) -> bytes:
    resp = _vault_request("POST", f"{_mount()}/decrypt/{name}", {"ciphertext": ciphertext})
    plaintext_b64 = resp.get("data", {}).get("plaintext")
    if not isinstance(plaintext_b64, str):
        raise ProviderError("vault decrypt did not return plaintext")
    dek = base64.b64decode(plaintext_b64)
    if len(dek) != 32:
        raise ProviderError("unwrapped data key is not 32 bytes")
    return dek


def get_or_create_key(req: dict[str, Any]) -> dict[str, Any]:
    key_id = str(req["key_id"])
    name = _transit_key_name(key_id)
    wrap_path = _wrap_path(key_id)
    _ensure_transit_key(name)
    if wrap_path.exists():
        record = json.loads(wrap_path.read_text(encoding="utf-8"))
        dek = _unwrap_dek(name, str(record["ciphertext"]))
        return {"key": _b64(dek)}
    dek = os.urandom(32)
    ciphertext = _wrap_dek(name, dek)
    record = {
        "version": 1,
        "tenant_id": req.get("tenant_id"),
        "cid": req.get("cid"),
        "key_id": key_id,
        "transit_key": name,
        "ciphertext": ciphertext,
    }
    tmp = wrap_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(wrap_path)
    return {"key": _b64(dek)}


def get_key(req: dict[str, Any]) -> dict[str, Any]:
    key_id = str(req["key_id"])
    name = _transit_key_name(key_id)
    wrap_path = _wrap_path(key_id)
    if not wrap_path.exists():
        raise ProviderError("object key is unavailable or has been shredded")
    if not _transit_key_exists(name):
        raise ProviderError("object key has been crypto-shredded (transit key deleted)")
    record = json.loads(wrap_path.read_text(encoding="utf-8"))
    dek = _unwrap_dek(name, str(record["ciphertext"]))
    return {"key": _b64(dek)}


def has_key(req: dict[str, Any]) -> dict[str, Any]:
    key_id = str(req["key_id"])
    name = _transit_key_name(key_id)
    exists = _wrap_path(key_id).exists() and _transit_key_exists(name)
    return {"exists": bool(exists)}


def rotate_key(req: dict[str, Any]) -> dict[str, Any]:
    """Rotate the per-object KEK (extra action used by validation).

    Advances the transit key version. Existing wrapped DEKs stay decryptable;
    a subsequent rewrap can upgrade them via transit/rewrap.
    """
    key_id = str(req["key_id"])
    name = _transit_key_name(key_id)
    if not _transit_key_exists(name):
        raise ProviderError("cannot rotate a missing/shredded key")
    _vault_request("POST", f"{_mount()}/keys/{name}/rotate", {})
    info = _vault_request("GET", f"{_mount()}/keys/{name}")
    version = info.get("data", {}).get("latest_version")
    # Rewrap the stored ciphertext to the latest key version.
    wrap_path = _wrap_path(key_id)
    if wrap_path.exists():
        record = json.loads(wrap_path.read_text(encoding="utf-8"))
        resp = _vault_request(
            "POST", f"{_mount()}/rewrap/{name}", {"ciphertext": str(record["ciphertext"])}
        )
        new_ct = resp.get("data", {}).get("ciphertext")
        if isinstance(new_ct, str):
            record["ciphertext"] = new_ct
            wrap_path.write_text(json.dumps(record, sort_keys=True, indent=2), encoding="utf-8")
    return {"rotated": True, "latest_version": version}


def shred_key(req: dict[str, Any]) -> dict[str, Any]:
    key_id = str(req["key_id"])
    name = _transit_key_name(key_id)
    wrap_path = _wrap_path(key_id)
    existed = wrap_path.exists() or _transit_key_exists(name)
    # Delete the Vault transit key first: this is the real crypto-erase. Once
    # the KEK is gone the wrapped DEK can never be unwrapped.
    if _transit_key_exists(name):
        _vault_request("POST", f"{_mount()}/keys/{name}/config", {"deletion_allowed": True})
        try:
            _vault_request("DELETE", f"{_mount()}/keys/{name}")
        except ProviderError as exc:
            raise ProviderError(f"vault key deletion failed: {exc}") from exc
    if wrap_path.exists():
        wrap_path.unlink()
    return {"shredded": bool(existed)}


_ACTIONS = {
    "get_or_create_key": get_or_create_key,
    "get_key": get_key,
    "has_key": has_key,
    "shred_key": shred_key,
    "rotate": rotate_key,
    "rotate_key": rotate_key,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"error": "missing action argument"}), file=sys.stderr)
        return 2
    action = argv[-1]
    handler = _ACTIONS.get(action)
    if handler is None:
        print(json.dumps({"error": f"unknown action: {action}"}), file=sys.stderr)
        return 2
    raw = sys.stdin.read() or "{}"
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid request json: {exc}"}), file=sys.stderr)
        return 2
    if not isinstance(req, dict):
        print(json.dumps({"error": "request must be a JSON object"}), file=sys.stderr)
        return 2
    req.setdefault("action", action)
    if "key_id" not in req:
        # Derive key_id the same way Mnemosyne does if omitted (e.g. manual run).
        tenant_id = str(req.get("tenant_id", ""))
        cid = str(req.get("cid", ""))
        req["key_id"] = hashlib.sha256(f"{tenant_id}:{cid}".encode("utf-8")).hexdigest()
    try:
        result = handler(req)
    except ProviderError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    except KeyError as exc:
        print(json.dumps({"error": f"missing field: {exc}"}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
