"""Persistence and fail-closed semantic verification for deletion manifests."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .evidence_signing import sign_evidence_manifest, verify_evidence_manifest_signature

SCHEMA = "mnemosyne.deletion_manifest.v1"
_RAW_HASH = re.compile(r"^[0-9a-fA-F]{32,}$")
_OPAQUE_REF = re.compile(r"^opaque:[0-9a-f]{64}$")
_CHECKPOINT = re.compile(r"^(?:[0-9a-f]{16}|local:[1-9][0-9]*)$")
_FORBIDDEN_KEYS = {
    "payload", "content", "content_pointer", "source_uri", "uri", "hash",
    "tenant_id", "user_id", "source_ref", "evidence_cid", "source_identity",
}
_ALLOWED_KEYS = {
    "manifest": {
        "schema", "operation_id", "request_id", "requested_at", "completed_at",
        "mode", "requested_by_role", "reason", "tenant_ref", "user_scope",
        "branch_scope", "source_refs", "policy", "fence", "surfaces", "stores",
        "retention_exceptions", "summary",
    },
    "policy": {"version", "required_surfaces"},
    "fence": {"generation", "ledger_position", "durable"},
    "surface": {
        "surface", "surface_type", "backend", "tenant_ref", "object_ref", "action",
        "precondition_present", "attempted_at", "verified_at", "verification_method",
        "state", "attempts", "checkpoint", "verified_removed", "residue_probe",
        "durability_checkpoint", "error_code",
    },
    "store": {"store", "surface_type", "expected", "discovered", "visited", "available", "checkpoint"},
    "retention_exception": {"surface", "restore_block_fence", "deadline"},
    "summary": {
        "expected", "visited", "verified", "failed", "unavailable", "cascade_percent",
        "recoverable_residue_count", "cross_tenant_mutations", "complete",
    },
}
_REQUIRED_KEYS = {
    "manifest": _ALLOWED_KEYS["manifest"],
    "policy": _ALLOWED_KEYS["policy"],
    "fence": _ALLOWED_KEYS["fence"],
    "surface": _ALLOWED_KEYS["surface"],
    "store": _ALLOWED_KEYS["store"],
    "summary": _ALLOWED_KEYS["summary"],
}


def _schema_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def check(value: Any, kind: str, path: str) -> None:
        if not isinstance(value, dict):
            return
        unknown = set(value) - _ALLOWED_KEYS[kind]
        if unknown:
            errors.append(f"{path} contains unknown fields: {', '.join(sorted(map(str, unknown)))}")
        required = _REQUIRED_KEYS.get(kind, set())
        missing = required - set(value)
        if missing:
            errors.append(f"{path} lacks required fields: {', '.join(sorted(missing))}")

    check(manifest, "manifest", "manifest")
    for field, kind in (("policy", "policy"), ("fence", "fence"), ("summary", "summary")):
        check(manifest.get(field), kind, f"manifest.{field}")
    for field, kind in (("surfaces", "surface"), ("stores", "store"), ("retention_exceptions", "retention_exception")):
        rows = manifest.get(field)
        if isinstance(rows, list):
            for index, row in enumerate(rows):
                check(row, kind, f"manifest.{field}[{index}]")
    return errors


def _custody_errors(value: Any, *, path: str = "manifest") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_KEYS:
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
    if not isinstance(value, str) or _OPAQUE_REF.fullmatch(value) is None:
        errors.append(f"{key} must be opaque")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _receipt_timestamps_valid(
    row: dict[str, Any], requested_at: datetime | None, completed_at: datetime | None
) -> bool:
    attempted_at = _timestamp(row.get("attempted_at"))
    verified_at = _timestamp(row.get("verified_at"))
    return (
        requested_at is not None
        and attempted_at is not None
        and verified_at is not None
        and completed_at is not None
        and requested_at <= attempted_at <= verified_at <= completed_at
    )


def verify_deletion_manifest(manifest: Any) -> dict[str, Any]:
    """Verify deletion meaning; a valid detached signature alone is insufficient."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return {"complete": False, "errors": ["manifest must be an object"]}
    if manifest.get("schema") != SCHEMA:
        errors.append("schema is unsupported")
    errors.extend(_schema_errors(manifest))
    errors.extend(_custody_errors(manifest))
    for field in ("tenant_ref", "user_scope", "reason"):
        _opaque_field(manifest, field, errors)
    try:
        operation_id = UUID(manifest.get("operation_id", ""))
    except (TypeError, ValueError):
        operation_id = None
    if operation_id is None or manifest.get("request_id") != str(operation_id):
        errors.append("operation and request identifiers must name the same UUID")
    requested_at = _timestamp(manifest.get("requested_at"))
    completed_at = _timestamp(manifest.get("completed_at"))
    if requested_at is None or completed_at is None or completed_at < requested_at:
        errors.append("manifest timestamps must prove ordered completion")
    if manifest.get("mode") != "hard_delete_legal":
        errors.append("deletion mode is unsupported")
    if manifest.get("requested_by_role") != "legal":
        errors.append("deletion manifest lacks legal authorization semantics")
    if manifest.get("branch_scope") not in {"main", "all"}:
        errors.append("branch scope is unsupported")

    surfaces = manifest.get("surfaces")
    stores = manifest.get("stores")
    summary = manifest.get("summary")
    fence = manifest.get("fence")
    policy = manifest.get("policy")
    if not isinstance(policy, dict) or policy.get("version") != "w2":
        errors.append("deletion policy version is unsupported")
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
        type(fence.get(key)) is int and fence[key] > 0
        for key in ("generation", "ledger_position")
    ):
        errors.append("fence must identify a positive durable ledger position")
    elif fence.get("durable") is not True:
        errors.append("fence is not durable")

    surface_values = [
        (row.get("surface_type"), row.get("surface"))
        for row in surfaces
        if isinstance(row, dict)
    ]
    store_values = [
        (row.get("surface_type"), row.get("store"))
        for row in stores
        if isinstance(row, dict)
    ]
    required = policy.get("required_surfaces") if isinstance(policy, dict) else None
    required_values = [
        (row.get("surface_type"), row.get("surface"))
        for row in required or []
        if isinstance(row, dict)
    ]
    names_are_valid = all(
        isinstance(kind, str) and bool(kind.strip())
        and isinstance(name, str) and bool(name.strip())
        for values in (surface_values, store_values, required_values)
        for kind, name in values
    )
    if not names_are_valid:
        errors.append("surface and store names must be nonempty strings")
    surface_names = set(surface_values) if names_are_valid else set()
    store_names = set(store_values) if names_are_valid else set()
    required_names = set(required_values) if isinstance(required, list) and names_are_valid else set()
    if (
        not isinstance(required, list)
        or not required
        or len(required_values) != len(required)
        or len(required) != len(required_names)
        or len(surface_values) != len(surface_names)
        or len(store_values) != len(store_names)
        or required_names != surface_names
        or required_names != store_names
    ):
        errors.append("required surfaces are not fully enumerated")
    if any(
        not isinstance(row, dict)
        or row.get("action") not in {"deleted", "invalidated", "crypto_shredded"}
        or row.get("state") != "verified"
        or row.get("precondition_present") is not True
        or row.get("verification_method") != "direct_and_public_probe"
        or not _receipt_timestamps_valid(row, requested_at, completed_at)
        or type(row.get("attempts")) is not int
        or row["attempts"] < 1
        or not isinstance(row.get("checkpoint"), str)
        or _CHECKPOINT.fullmatch(row["checkpoint"]) is None
        or row.get("verified_removed") is not True
        or row.get("residue_probe") != 0
        or not isinstance(row.get("durability_checkpoint"), str)
        or _CHECKPOINT.fullmatch(row["durability_checkpoint"]) is None
        or row.get("durability_checkpoint") != row.get("checkpoint")
        or row.get("backend") not in {"local", "synthetic"}
        or row.get("error_code") is not None
        for row in surfaces
    ):
        errors.append("one or more surfaces lack verified durable removal")
    if any(
        not isinstance(row.get("tenant_ref"), str)
        or _OPAQUE_REF.fullmatch(row["tenant_ref"]) is None
        or not isinstance(row.get("object_ref"), str)
        or _OPAQUE_REF.fullmatch(row["object_ref"]) is None
        for row in surfaces
        if isinstance(row, dict)
    ):
        errors.append("surface custody references must be opaque")
    if any(
        not isinstance(row, dict)
        or any(type(row.get(field)) is not int or row[field] < 0 for field in ("expected", "discovered", "visited"))
        or row.get("available") is not True
        or row.get("visited") != row.get("expected")
        or row.get("discovered") != row.get("expected")
        or not isinstance(row.get("checkpoint"), str)
        or _CHECKPOINT.fullmatch(row["checkpoint"]) is None
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
        not isinstance(ref, str) or _OPAQUE_REF.fullmatch(ref) is None
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
