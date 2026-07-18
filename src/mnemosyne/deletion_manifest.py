"""Persistence and fail-closed semantic verification for deletion manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evidence_signing import sign_evidence_manifest, verify_evidence_manifest_signature

SCHEMA = "mnemosyne.deletion_manifest.v1"
_RAW_HASH = re.compile(r"^[0-9a-fA-F]{32,}$")
_FORBIDDEN_KEYS = {
    "payload", "content", "content_pointer", "source_uri", "uri", "hash",
    "tenant_id", "user_id", "source_ref", "evidence_cid", "source_identity",
}


def _custody_errors(value: Any, *, path: str = "manifest") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS:
                errors.append(f"{path}.{key} is a forbidden direct-custody field")
            errors.extend(_custody_errors(item, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_custody_errors(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        if "canary" in lowered:
            errors.append(f"{path} contains canary material")
        if "://" in value:
            errors.append(f"{path} contains a source URI")
        if _RAW_HASH.fullmatch(value) and not value.startswith("opaque:"):
            errors.append(f"{path} contains a direct hash")
    return errors


def _opaque_field(manifest: dict[str, Any], key: str, errors: list[str]) -> None:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.startswith("opaque:"):
        errors.append(f"{key} must be opaque")


def verify_deletion_manifest(manifest: Any) -> dict[str, Any]:
    """Verify deletion meaning; a valid detached signature alone is insufficient."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return {"complete": False, "errors": ["manifest must be an object"]}
    if manifest.get("schema") != SCHEMA:
        errors.append("schema is unsupported")
    errors.extend(_custody_errors(manifest))
    for field in ("tenant_ref", "user_scope", "reason"):
        _opaque_field(manifest, field, errors)

    surfaces = manifest.get("surfaces")
    stores = manifest.get("stores")
    summary = manifest.get("summary")
    fence = manifest.get("fence")
    policy = manifest.get("policy")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append("surfaces must be nonempty")
        surfaces = []
    if not isinstance(stores, list) or not stores:
        errors.append("stores must be nonempty")
        stores = []
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
        summary = {}
    if not isinstance(fence, dict) or not all(
        isinstance(fence.get(key), int) and fence[key] > 0
        for key in ("generation", "ledger_position")
    ):
        errors.append("fence must identify a positive durable ledger position")
    elif fence.get("durable") is not True:
        errors.append("fence is not durable")

    surface_values = [row.get("surface") for row in surfaces if isinstance(row, dict)]
    store_values = [row.get("store") for row in stores if isinstance(row, dict)]
    surface_names = set(surface_values)
    store_names = set(store_values)
    required = policy.get("required_surfaces") if isinstance(policy, dict) else None
    required_names = set(required) if isinstance(required, list) else set()
    if (
        not isinstance(required, list)
        or not required
        or len(required) != len(required_names)
        or len(surface_values) != len(surface_names)
        or len(store_values) != len(store_names)
        or required_names != surface_names
        or required_names != store_names
    ):
        errors.append("required surfaces are not fully enumerated")
    if any(
        not isinstance(row, dict)
        or row.get("verified_removed") is not True
        or row.get("residue_probe") != 0
        or not row.get("durability_checkpoint")
        or row.get("error_code") is not None
        for row in surfaces
    ):
        errors.append("one or more surfaces lack verified durable removal")
    if any(
        not isinstance(row.get("tenant_ref"), str)
        or not row["tenant_ref"].startswith("opaque:")
        or not isinstance(row.get("object_ref"), str)
        or not row["object_ref"].startswith("opaque:")
        for row in surfaces
        if isinstance(row, dict)
    ):
        errors.append("surface custody references must be opaque")
    if any(
        not isinstance(row, dict)
        or row.get("available") is not True
        or row.get("visited") != row.get("expected")
        or row.get("discovered") != row.get("expected")
        or not row.get("checkpoint")
        for row in stores
    ):
        errors.append("one or more stores are incomplete or unavailable")

    expected = len(surfaces)
    required_summary = {
        "expected": expected,
        "visited": expected,
        "verified": expected,
        "failed": 0,
        "unavailable": 0,
        "cascade_percent": 100,
        "recoverable_residue_count": 0,
        "cross_tenant_mutations": 0,
        "complete": True,
    }
    if any(summary.get(key) != value for key, value in required_summary.items()):
        errors.append("summary does not prove complete zero-residue deletion")
    if manifest.get("retention_exceptions") != []:
        errors.append("retention exceptions remain")
    if not manifest.get("source_refs") or any(
        not isinstance(ref, str) or not ref.startswith("opaque:")
        for ref in manifest.get("source_refs", [])
    ):
        errors.append("source references must be nonempty and opaque")
    return {"complete": not errors, "errors": errors}


def write_signed_deletion_manifest(
    manifest: dict[str, Any], manifest_path: Path, private_key_path: Path
) -> dict[str, Any]:
    """Persist a semantically complete manifest and sign its exact bytes."""
    result = verify_deletion_manifest(manifest)
    if not result["complete"]:
        raise ValueError("refusing to sign semantically incomplete deletion manifest: " + "; ".join(result["errors"]))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sign_evidence_manifest(manifest_path, private_key_path)


def verify_signed_deletion_manifest(
    manifest_path: Path, public_key_path: Path
) -> dict[str, Any]:
    """Require both a valid collector signature and complete deletion semantics."""
    signature = verify_evidence_manifest_signature(manifest_path, public_key_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    semantic = verify_deletion_manifest(manifest)
    signature_verified = signature.get("verified") is True
    errors = list(semantic["errors"])
    if not signature_verified:
        errors.append("manifest signature is invalid")
    return {"complete": semantic["complete"] and signature_verified, "errors": errors, "signature": signature}
