#!/usr/bin/env python3
"""Vault-transit HMAC adapter for the append-only audit hash chain.

Reads the chain-head sha256 hex digest on stdin and prints Vault's HMAC token
(``vault:v1:...``) on stdout, computed by the ``mnemosyne-audit`` transit key.
The HMAC key never leaves Vault, so an attacker who rewrites audit rows cannot
recompute the retained head anchor. Wire it in via
``MNEMOSYNE_AUDIT_HMAC_COMMAND="python3 infra/vault/audit-hmac-adapter.py"`` for
``ops-report``/``audit-chain-export``/``audit-chain-verify``.

Environment:
  VAULT_ADDR                              Vault API base URL (required).
  VAULT_CACERT                            CA bundle for TLS verification (required).
  MNEMOSYNE_AUDIT_HMAC_VAULT_TOKEN_FILE   File holding a token scoped to
                                          transit/hmac on the audit key (falls
                                          back to VAULT_TOKEN_FILE).
  MNEMOSYNE_AUDIT_HMAC_TRANSIT_KEY        Transit key name (default mnemosyne-audit).

No secret is baked into this file; the token lives out-of-repo.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def _fail(message: str) -> "None":
    sys.stderr.write(f"audit-hmac-adapter: {message}\n")
    raise SystemExit(1)


def main() -> None:
    addr = os.environ.get("VAULT_ADDR")
    cacert = os.environ.get("VAULT_CACERT")
    if not addr:
        _fail("VAULT_ADDR is required")
    token_file = os.environ.get("MNEMOSYNE_AUDIT_HMAC_VAULT_TOKEN_FILE") or os.environ.get("VAULT_TOKEN_FILE")
    if not token_file:
        _fail("MNEMOSYNE_AUDIT_HMAC_VAULT_TOKEN_FILE (or VAULT_TOKEN_FILE) is required")
    try:
        token = open(token_file, encoding="utf-8").read().strip()
    except OSError as exc:
        _fail(f"cannot read token file: {exc}")
    key = os.environ.get("MNEMOSYNE_AUDIT_HMAC_TRANSIT_KEY", "mnemosyne-audit")

    message = sys.stdin.buffer.read()
    if not message:
        _fail("no chain-head message on stdin")

    ctx = ssl.create_default_context(cafile=cacert) if cacert else ssl.create_default_context()
    body = json.dumps({"input": base64.b64encode(message).decode("ascii")}).encode("ascii")
    request = urllib.request.Request(
        f"{addr.rstrip('/')}/v1/transit/hmac/{key}/sha2-256",
        data=body,
        method="POST",
        headers={"X-Vault-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=ctx, timeout=30) as resp:
            payload = json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as exc:
        _fail(f"Vault transit HMAC HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}")
    except Exception as exc:  # noqa: BLE001 - any transport failure must fail closed
        _fail(f"Vault transit HMAC request failed: {exc}")

    hmac_token = (payload.get("data") or {}).get("hmac")
    if not hmac_token:
        _fail("Vault transit HMAC response missing data.hmac")
    sys.stdout.write(hmac_token)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
