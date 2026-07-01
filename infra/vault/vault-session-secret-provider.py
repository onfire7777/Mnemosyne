#!/usr/bin/env python3
"""Vault-KV-backed session-secret provider for Mnemosyne.

Implements ``security.load_session_secret_command``'s contract: invoked with
``get_session_secret`` appended to argv and a JSON request on stdin, it must
print exactly one of::

    {"secret": "<hmac secret>"}
    {"keyring": {"<kid>": "<secret>", ...}, "active_key_id": "<kid>"}

The keyring lives in Vault KV v2 at ``secret/data/mnemosyne/session-keyring``
(fields: ``keyring`` JSON object + ``active_key_id``), so rotation is a Vault
write — no service env changes. Raw secrets never rest in the repo.

Environment:
    VAULT_ADDR          e.g. https://vault.mnemo.local:8200
    VAULT_TOKEN         token scoped to read the KV path (or VAULT_TOKEN_FILE)
    VAULT_CACERT        CA bundle for the step-ca chain
    MNEMOSYNE_VAULT_SESSION_KV_PATH   override KV path
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request


def main() -> int:
    address = os.environ.get("VAULT_ADDR", "https://vault.mnemo.local:8200").rstrip("/")
    token = os.environ.get("VAULT_TOKEN", "")
    token_file = os.environ.get("VAULT_TOKEN_FILE")
    if not token and token_file:
        token = open(token_file, encoding="utf-8").read().strip()
    if not token:
        print("vault-session-secret: VAULT_TOKEN(_FILE) is required", file=sys.stderr)
        return 78
    path = os.environ.get(
        "MNEMOSYNE_VAULT_SESSION_KV_PATH", "secret/data/mnemosyne/session-keyring"
    )
    context = ssl.create_default_context(cafile=os.environ.get("VAULT_CACERT"))
    request = urllib.request.Request(
        f"{address}/v1/{path}", headers={"X-Vault-Token": token}
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            payload = json.load(response)
    except Exception as exc:  # fail closed
        print(f"vault-session-secret: vault read failed: {exc}", file=sys.stderr)
        return 1
    data = (payload.get("data") or {}).get("data") or {}
    keyring = data.get("keyring")
    if isinstance(keyring, str):
        keyring = json.loads(keyring)
    active = data.get("active_key_id")
    if not isinstance(keyring, dict) or not keyring or not active:
        print("vault-session-secret: keyring/active_key_id missing in KV", file=sys.stderr)
        return 1
    json.dump({"keyring": keyring, "active_key_id": str(active)}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
