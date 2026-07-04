"""Tamper-evident hash chaining for the append-only audit log.

Each audit entry is canonicalized and folded into a hash chain; the chain head
is anchored with an HMAC produced outside the database — Vault transit in
production (``vault-hmac`` via a command adapter, so the key never leaves
Vault), or an explicitly non-production local secret for development. An
attacker who can rewrite audit rows cannot recompute the retained head anchor
without the external HMAC key, so edits surface on verification.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_module
import json
import shlex
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

AUDIT_CHAIN_SCHEMA = "mnemosyne.audit_hash_chain.v1"
AUDIT_CHAIN_GENESIS = "0" * 64
VAULT_HMAC_PROVIDER = "vault-hmac"
LOCAL_HMAC_PROVIDER = "local-hmac"

HmacProvider = Callable[[str], str]


class AuditChainError(ValueError):
    """Raised when chain construction or verification fails closed."""


def canonical_entry_sha256(entry: Any) -> str:
    try:
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise AuditChainError(f"audit entry is not canonical JSON: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fold(prev_link_sha256: str, entry_sha256: str) -> str:
    return hashlib.sha256(f"{prev_link_sha256}:{entry_sha256}".encode("ascii")).hexdigest()


def command_hmac_provider(command: str, *, timeout: float = 30.0) -> HmacProvider:
    """HMAC via an external adapter (Vault transit in production).

    The adapter receives the chain-head sha256 hex digest on stdin and must
    print the HMAC token (e.g. Vault's ``vault:v1:...``) on stdout. The HMAC
    key itself never enters this process."""
    argv = shlex.split(command)
    if not argv:
        raise AuditChainError("audit HMAC command must be non-empty")

    def provider(message: str) -> str:
        try:
            completed = subprocess.run(
                argv,
                input=message.encode("ascii"),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuditChainError(f"audit HMAC command failed: {exc}") from exc
        if completed.returncode != 0:
            raise AuditChainError(f"audit HMAC command exited {completed.returncode}")
        token = completed.stdout.decode("utf-8", errors="replace").strip()
        if not token:
            raise AuditChainError("audit HMAC command produced no output")
        return token

    return provider


def local_hmac_provider(secret: str) -> HmacProvider:
    """Development-only anchor; never satisfies the production vault-hmac gate."""
    if not secret:
        raise AuditChainError("local audit HMAC secret must be non-empty")
    key = secret.encode("utf-8")

    def provider(message: str) -> str:
        return "local:" + hmac_module.new(key, message.encode("ascii"), hashlib.sha256).hexdigest()

    return provider


def build_audit_chain(
    entries: Sequence[Any],
    *,
    tenant_id: str,
    provider_name: str,
    hmac_provider: HmacProvider,
) -> dict[str, Any]:
    links: list[dict[str, Any]] = []
    prev = AUDIT_CHAIN_GENESIS
    for index, entry in enumerate(entries):
        entry_sha256 = canonical_entry_sha256(entry)
        link_sha256 = _fold(prev, entry_sha256)
        links.append({"index": index, "entry_sha256": entry_sha256, "link_sha256": link_sha256})
        prev = link_sha256
    head_hmac = hmac_provider(prev)
    return {
        "schema": AUDIT_CHAIN_SCHEMA,
        "provider": provider_name,
        "non_production": provider_name != VAULT_HMAC_PROVIDER,
        "tenant_id": tenant_id,
        "entry_count": len(links),
        "genesis": AUDIT_CHAIN_GENESIS,
        "links": links,
        "head_link_sha256": prev,
        "head_hmac": head_hmac,
    }


def verify_audit_chain(
    document: Any,
    entries: Sequence[Any],
    *,
    tenant_id: str,
    hmac_provider: HmacProvider,
) -> dict[str, Any]:
    """Recompute the chain from live entries and check it against the retained
    document, including the externally-anchored head HMAC. Every failure raises
    ``AuditChainError`` so callers can only treat verified chains as intact."""
    if not isinstance(document, dict):
        raise AuditChainError("audit chain document must be a JSON object")
    if document.get("schema") != AUDIT_CHAIN_SCHEMA:
        raise AuditChainError("audit chain schema is unsupported")
    if document.get("tenant_id") != tenant_id:
        raise AuditChainError("audit chain document tenant does not match")
    recorded_links = document.get("links")
    if not isinstance(recorded_links, list):
        raise AuditChainError("audit chain document requires links")
    if int(document.get("entry_count") or -1) != len(entries):
        raise AuditChainError(
            f"audit chain entry count mismatch: retained {document.get('entry_count')}, live {len(entries)}"
        )
    if len(recorded_links) != len(entries):
        raise AuditChainError("audit chain link count does not match live entries")
    prev = AUDIT_CHAIN_GENESIS
    for index, (entry, recorded) in enumerate(zip(entries, recorded_links, strict=True)):
        entry_sha256 = canonical_entry_sha256(entry)
        link_sha256 = _fold(prev, entry_sha256)
        if not isinstance(recorded, dict):
            raise AuditChainError(f"audit chain link {index} is malformed")
        if recorded.get("entry_sha256") != entry_sha256:
            raise AuditChainError(f"audit entry {index} does not match its retained chain digest")
        if recorded.get("link_sha256") != link_sha256:
            raise AuditChainError(f"audit chain link {index} does not fold to the retained digest")
        prev = link_sha256
    if document.get("head_link_sha256") != prev:
        raise AuditChainError("audit chain head does not match the recomputed chain")
    expected_hmac = hmac_provider(prev)
    recorded_hmac = str(document.get("head_hmac") or "")
    if not recorded_hmac or not hmac_module.compare_digest(expected_hmac, recorded_hmac):
        raise AuditChainError("audit chain head HMAC anchor does not verify")
    return {
        "schema": AUDIT_CHAIN_SCHEMA,
        "provider": document.get("provider"),
        "tenant_id": tenant_id,
        "entry_count": len(entries),
        "head_link_sha256": prev,
        "verified": True,
    }
