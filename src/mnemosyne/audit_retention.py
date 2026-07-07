"""Assemble release-audit retention evidence for the ops-report ``audit`` section.

``release-audit`` (see ``_release_ops_report_evidence_findings`` in the CLI)
rejects ops-report evidence unless, over the live append-only ``audit_log``, it
proves:

* ``hash_chain`` — a Vault-HMAC-anchored hash chain that *verifies* and is
  *retained* to a durable store;
* ``pgaudit`` — pgaudit *enabled* on the live database with *retained* output;
* ``worm_copy`` — an *external*, object-locked (immutable) copy that is
  *retained*.

Nothing here fabricates a flag: each flag is only ``True`` when a genuine
build/verify/probe succeeds. Callers inject the HMAC provider, the retention
sink, the database probe result, and the WORM sink result, so the shaping logic
is unit-testable without live infra and the identical code path runs in
production. ``local-hmac`` chains verify but can never satisfy the gate because
``audit_evidence_complete`` requires the ``vault-hmac`` provider.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mnemosyne.audit_chain import (
    VAULT_HMAC_PROVIDER,
    AuditChainError,
    build_audit_chain,
    verify_audit_chain,
)

HmacProvider = Callable[[str], str]
# A retention sink persists the verified chain document durably and returns a
# metadata mapping; ``retained`` must be ``True`` for the flag to be set.
RetentionSink = Callable[[dict[str, Any]], dict[str, Any]]


def hash_chain_evidence(
    entries: Sequence[Any],
    *,
    tenant_id: str,
    provider_name: str,
    hmac_provider: HmacProvider,
    retain: RetentionSink | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build, verify and (optionally) retain a hash chain over ``entries``.

    Returns ``(evidence, document)``. ``evidence['verified']`` is ``True`` only
    when :func:`verify_audit_chain` re-derives the chain and the external HMAC
    head anchor matches. ``evidence['retained']`` is ``True`` only when
    ``retain`` persists the document and reports ``retained: True``. ``document``
    is the retained chain object (or ``None`` if construction failed), so a WORM
    sink can archive the exact same bytes.
    """
    evidence: dict[str, Any] = {
        "provider": provider_name,
        "verified": False,
        "retained": False,
    }
    try:
        document = build_audit_chain(
            entries,
            tenant_id=tenant_id,
            provider_name=provider_name,
            hmac_provider=hmac_provider,
        )
        verify_audit_chain(
            document,
            entries,
            tenant_id=tenant_id,
            hmac_provider=hmac_provider,
        )
    except AuditChainError as exc:
        evidence["error"] = str(exc)
        return evidence, None

    evidence["verified"] = True
    evidence["entry_count"] = document["entry_count"]
    evidence["head_link_sha256"] = document["head_link_sha256"]

    if retain is not None:
        try:
            meta = retain(document)
        except Exception as exc:  # noqa: BLE001 - sink defines its own failure surface
            evidence["error"] = f"retention failed: {exc}"
            return evidence, document
        if isinstance(meta, dict) and meta.get("retained") is True:
            evidence["retained"] = True
            retention = {key: value for key, value in meta.items() if key != "retained"}
            if retention:
                evidence["retention"] = retention
        elif isinstance(meta, dict) and meta.get("error"):
            evidence["error"] = str(meta["error"])

    return evidence, document


def pgaudit_evidence(*, enabled: bool, retained: bool, **details: Any) -> dict[str, Any]:
    """Shape a pgaudit probe result. ``enabled``/``retained`` come from a live
    query against the database (extension installed + preloaded + logging
    configured; output on a durable retained destination)."""
    evidence: dict[str, Any] = {"enabled": bool(enabled), "retained": bool(retained)}
    for key, value in details.items():
        if value is not None:
            evidence[key] = value
    return evidence


def worm_copy_evidence(
    *, enabled: bool, external: bool, retained: bool, **details: Any
) -> dict[str, Any]:
    """Shape a WORM object-lock probe result. ``enabled``/``external``/
    ``retained`` come from putting the chain object into an object-lock bucket
    and reading its retention back from the external object store."""
    evidence: dict[str, Any] = {
        "enabled": bool(enabled),
        "external": bool(external),
        "retained": bool(retained),
    }
    for key, value in details.items():
        if value is not None:
            evidence[key] = value
    return evidence


def audit_section(
    hash_chain: dict[str, Any],
    pgaudit: dict[str, Any],
    worm_copy: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the ops-report ``audit`` section from the three evidences."""
    return {"hash_chain": hash_chain, "pgaudit": pgaudit, "worm_copy": worm_copy}


def audit_evidence_complete(audit: dict[str, Any]) -> bool:
    """Mirror the release-audit gate: all three retention proofs must hold.

    Kept in lockstep with ``_release_ops_report_evidence_findings`` so ops-report
    only reports ``ok`` when the same evidence the gate demands is genuinely
    present. This never weakens the gate — the gate remains the authority; this
    is a fail-closed self-check on the producer side.
    """
    hash_chain = audit.get("hash_chain")
    if not isinstance(hash_chain, dict):
        return False
    if str(hash_chain.get("provider") or "").lower() != VAULT_HMAC_PROVIDER:
        return False
    if hash_chain.get("verified") is not True or hash_chain.get("retained") is not True:
        return False

    pgaudit = audit.get("pgaudit")
    if not isinstance(pgaudit, dict):
        return False
    if pgaudit.get("enabled") is not True or pgaudit.get("retained") is not True:
        return False

    worm_copy = audit.get("worm_copy")
    if not isinstance(worm_copy, dict):
        return False
    if (
        worm_copy.get("enabled") is not True
        or worm_copy.get("external") is not True
        or worm_copy.get("retained") is not True
    ):
        return False

    return True
