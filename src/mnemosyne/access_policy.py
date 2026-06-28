"""Read-side access-policy enforcement helpers.

The privacy lane treats ``access_policy`` as a narrowing envelope. This module
keeps that contract shared between local and Postgres retrieval so one backend
cannot drift into a wider disclosure boundary than the other.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

ROLE_SENSITIVITY_CEILINGS: dict[str, int] = {
    "reader": 1,
    "agent": 2,
    "consolidator": 3,
    # Operator gets metadata/fingerprint authority by default. Raw S2+ requires
    # item-level and request-level break-glass, so the ordinary retrieval ceiling
    # stays at S1.
    "operator": 1,
}
ROLE_RANK: dict[str, int] = {"reader": 0, "agent": 1, "consolidator": 2, "operator": 3}

ALLOWED_ACCESS_POLICY_KEYS = {
    "allow_principals",
    "allow_roles",
    "allowed_residencies",
    "allowed_residency_transfers",
    "cross_region_transfer",
    "data_class",
    "embed_ok",
    "expires_at",
    "break_glass",
    "hold",
    "lawful_basis",
    "max_sensitivity",
    "min_role_for_raw",
    "purpose",
    "purposes",
    "redact_fields",
    "region",
    "regions",
    "require_capabilities",
    "residency",
    "residencies",
    "restricted",
    "runtime_residency",
    "scope",
    "scopes",
    "tenant",
    "tenant_id",
}


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str
    role: str
    ceiling: int
    redacted: bool = False
    unknown_keys: tuple[str, ...] = ()


VECTOR_PARTITION_PUBLIC = "public"
VECTOR_PARTITION_PRIVATE = "private"
VECTOR_PARTITION_NONE = "none"
VECTOR_PARTITIONS = {
    VECTOR_PARTITION_PUBLIC,
    VECTOR_PARTITION_PRIVATE,
    VECTOR_PARTITION_NONE,
}
_PRIVATE_VECTOR_DATA_CLASSES = {
    "biometric",
    "credential",
    "credentials",
    "financial",
    "health",
    "phi",
    "pii",
    "secret",
    "secrets",
    "sensitive",
    "sensitive_personal",
}


def role_for_context(context: Mapping[str, Any] | None) -> str:
    role = str((context or {}).get("role") or (context or {}).get("mnemosyne_role") or "reader").strip().lower()
    return role


def effective_max_sensitivity(context: Mapping[str, Any] | None, policy_max_sensitivity: int) -> int:
    """Return the caller's effective ceiling, never wider than role or policy."""

    role = role_for_context(context)
    role_ceiling = ROLE_SENSITIVITY_CEILINGS.get(role)
    if role_ceiling is None:
        return -1
    if role == "operator" and bool((context or {}).get("break_glass")):
        role_ceiling = max(role_ceiling, 3)
    ceiling = min(int(policy_max_sensitivity), role_ceiling)
    requested = (context or {}).get("max_sensitivity")
    if requested is not None:
        try:
            ceiling = min(ceiling, int(requested))
        except (TypeError, ValueError):
            return -1
    return max(-1, ceiling)


def unknown_access_policy_keys(access_policy: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return policy keys this runtime cannot enforce."""

    if not access_policy:
        return ()
    return tuple(
        sorted(
            str(key)
            for key in access_policy
            if not isinstance(key, str) or (key not in ALLOWED_ACCESS_POLICY_KEYS and not key.startswith("hold:"))
        )
    )


def validate_access_policy(
    access_policy: Mapping[str, Any] | None,
    *,
    tenant_id: str | None = None,
    location: str = "access_policy",
) -> dict[str, Any]:
    """Validate a write-time access-policy envelope before persistence.

    Unknown keys are rejected because they mean the writer expected a guard this
    runtime cannot enforce. Error messages intentionally include key names only,
    never policy values.
    """

    if access_policy is None:
        return {}
    if not isinstance(access_policy, Mapping):
        raise ValueError(f"{location} must be a JSON object")
    policy = dict(access_policy)
    unknown = unknown_access_policy_keys(policy)
    if unknown:
        raise ValueError(f"unknown {location} keys: {', '.join(unknown)}")

    policy_tenants = {
        str(policy[key])
        for key in ("tenant", "tenant_id")
        if key in policy and policy[key] not in (None, "")
    }
    if len(policy_tenants) > 1:
        raise ValueError(f"{location} tenant keys disagree")
    if tenant_id is not None and policy_tenants and next(iter(policy_tenants)) != str(tenant_id):
        raise ValueError(f"{location} tenant does not match row tenant")
    return policy


def may_embed_item(
    *,
    sensitivity: int,
    access_policy: Mapping[str, Any] | None,
    status: str = "active",
    erased: bool = False,
) -> bool:
    """Return whether an item may enter any embedding/vector channel."""

    return vector_partition_for_item(
        sensitivity=sensitivity,
        access_policy=access_policy,
        status=status,
        erased=erased,
    ) != VECTOR_PARTITION_NONE


def vector_partition_for_item(
    *,
    sensitivity: int,
    access_policy: Mapping[str, Any] | None,
    status: str = "active",
    erased: bool = False,
) -> str:
    """Return the fail-closed vector partition for a retrievable item.

    ``embed_ok: false`` means no embedding should be accepted or generated.
    Redaction/raw-role policies may still be retrievable textually, but their
    stored raw vectors are private and cannot be used for callers who only see
    a redacted projection.
    """

    policy = dict(access_policy or {})
    if unknown_access_policy_keys(policy):
        return VECTOR_PARTITION_NONE
    if erased or status not in {"active", "candidate", "contested"}:
        return VECTOR_PARTITION_NONE
    if policy.get("embed_ok") is False:
        return VECTOR_PARTITION_NONE
    if bool(policy.get("restricted")) or bool(policy.get("hold")) or any(
        str(key).startswith("hold:") and bool(value) for key, value in policy.items()
    ):
        return VECTOR_PARTITION_NONE
    if int(sensitivity) >= 4:
        return VECTOR_PARTITION_NONE

    if _raw_vector_restricted(policy, int(sensitivity)):
        return VECTOR_PARTITION_PRIVATE
    return VECTOR_PARTITION_PUBLIC


def may_use_stored_embedding(
    *,
    decision: AccessDecision,
    sensitivity: int,
    access_policy: Mapping[str, Any] | None,
    embedding_partition: str | None = None,
) -> bool:
    """Return whether a stored raw embedding may influence this caller's rank."""

    if not decision.allowed:
        return False
    partition = _normalise_vector_partition(embedding_partition)
    if partition is None:
        partition = vector_partition_for_item(sensitivity=sensitivity, access_policy=access_policy)
    if partition == VECTOR_PARTITION_NONE:
        return False
    if partition == VECTOR_PARTITION_PUBLIC:
        return True
    return not decision.redacted


def may_read_item(
    *,
    item_tenant_id: str,
    sensitivity: int,
    access_policy: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None,
    policy_max_sensitivity: int,
    status: str = "active",
    erased: bool = False,
) -> AccessDecision:
    """Evaluate the read predicate for one retrievable item.

    Denies are existence-silent at the caller layer; the reason is returned only
    for local explain/test metadata and never includes raw sensitive values.
    """

    ctx = dict(context or {})
    policy = dict(access_policy or {})
    role = role_for_context(ctx)
    ceiling = effective_max_sensitivity(ctx, policy_max_sensitivity)
    if role not in ROLE_RANK:
        return AccessDecision(False, "invalid_role", role, ceiling)
    unknown = unknown_access_policy_keys(policy)
    if unknown:
        return AccessDecision(False, "unknown_access_policy_key", role, ceiling, unknown_keys=unknown)
    if erased:
        return AccessDecision(False, "erased", role, ceiling)
    if status not in {"active", "candidate", "contested"}:
        return AccessDecision(False, "inactive_status", role, ceiling)
    ctx_tenant = str(ctx.get("tenant_id") or ctx.get("tenant") or "")
    policy_tenant = str(policy.get("tenant") or policy.get("tenant_id") or item_tenant_id)
    if ctx_tenant and ctx_tenant != item_tenant_id:
        return AccessDecision(False, "tenant_mismatch", role, ceiling)
    if policy_tenant and policy_tenant != item_tenant_id:
        return AccessDecision(False, "policy_tenant_mismatch", role, ceiling)
    if bool(policy.get("restricted")) or bool(policy.get("hold")) or any(
        str(key).startswith("hold:") and bool(value) for key, value in policy.items()
    ):
        return AccessDecision(False, "restricted", role, ceiling)
    if _expired(policy.get("expires_at")):
        return AccessDecision(False, "expired_access_policy", role, ceiling)

    if sensitivity >= 4:
        return AccessDecision(False, "s4_raw_not_retrievable", role, ceiling)

    break_glass = bool(ctx.get("break_glass")) and bool(policy.get("break_glass")) and role == "operator"
    if break_glass and sensitivity < 4:
        ceiling = max(ceiling, min(int(policy_max_sensitivity), 3))
    elif role == "operator" and sensitivity >= 2:
        return AccessDecision(False, "operator_break_glass_required", role, ceiling)

    policy_max = policy.get("max_sensitivity")
    if policy_max is not None:
        try:
            ceiling = min(ceiling, int(policy_max))
        except (TypeError, ValueError):
            return AccessDecision(False, "invalid_policy_max_sensitivity", role, ceiling)
    if sensitivity > ceiling:
        return AccessDecision(False, "sensitivity_ceiling", role, ceiling)

    allowed_roles = _str_set(policy.get("allow_roles"))
    if allowed_roles and role not in allowed_roles:
        return AccessDecision(False, "role_not_allowed", role, ceiling)
    required_caps = _str_set(policy.get("require_capabilities"))
    caller_caps = _str_set(ctx.get("capability_tags") or ctx.get("capabilities") or ctx.get("capability_set"))
    if required_caps and not required_caps.issubset(caller_caps):
        return AccessDecision(False, "missing_capability", role, ceiling)
    principals = _str_set(policy.get("allow_principals"))
    if principals:
        caller_principals = _str_set(
            [
                ctx.get("user_id"),
                ctx.get("subject"),
                ctx.get("principal"),
                ctx.get("source_identity"),
            ]
        )
        if principals.isdisjoint(caller_principals):
            return AccessDecision(False, "principal_not_allowed", role, ceiling)
    if not _scope_allows(policy.get("scope") or policy.get("scopes"), ctx.get("scope") or ctx.get("scopes")):
        return AccessDecision(False, "scope_mismatch", role, ceiling)
    if not _intersects_if_policy_set(policy.get("purpose") or policy.get("purposes"), ctx.get("purpose") or ctx.get("purposes")):
        return AccessDecision(False, "purpose_mismatch", role, ceiling)
    if not _residency_allows(policy, ctx):
        return AccessDecision(False, "residency_mismatch", role, ceiling)
    if not _intersects_if_policy_set(policy.get("lawful_basis"), ctx.get("lawful_basis")):
        return AccessDecision(False, "lawful_basis_mismatch", role, ceiling)

    redacted = False
    redact_fields = _str_list(policy.get("redact_fields"))
    min_raw = str(policy.get("min_role_for_raw") or "").strip().lower()
    if min_raw and min_raw not in ROLE_RANK:
        return AccessDecision(False, "invalid_min_role_for_raw", role, ceiling)
    if redact_fields and min_raw and ROLE_RANK.get(role, -1) < ROLE_RANK.get(min_raw, 99):
        redacted = True
    elif min_raw and ROLE_RANK.get(role, -1) < ROLE_RANK.get(min_raw, 99):
        return AccessDecision(False, "raw_role_required", role, ceiling)
    return AccessDecision(True, "allowed", role, ceiling, redacted=redacted)


def apply_text_redactions(text: str, access_policy: Mapping[str, Any] | None, decision: AccessDecision) -> tuple[str, dict[str, Any]]:
    fields = _str_list((access_policy or {}).get("redact_fields"))
    metadata = _redaction_metadata(decision)
    if not decision.redacted:
        return text, metadata
    if not fields:
        return _redaction_placeholder((), metadata)

    structured = _redact_json_text(text, fields)
    if structured is not None:
        redacted, structured_metadata = structured
        metadata.update(structured_metadata)
        return redacted, metadata

    redacted = text
    for field in fields:
        label = re.escape(field)
        redacted = re.sub(
            rf"(?i)(\b{label}\b\s*[:=]\s*)([^,;\n]+)",
            rf"\1[REDACTED:{field}]",
            redacted,
        )
    if redacted == text:
        return _redaction_placeholder(fields, metadata)
    else:
        metadata["redaction_mode"] = "label"
    metadata["redacted"] = True
    metadata["redact_fields"] = fields
    return redacted, metadata


def apply_statement_redactions(
    *,
    subject: str,
    predicate: str,
    object_value: str,
    access_policy: Mapping[str, Any] | None,
    decision: AccessDecision,
) -> tuple[str, dict[str, Any]]:
    record = {"subject": subject, "predicate": predicate, "object": object_value}
    structured = _apply_structured_record_redactions(record, ("subject", "predicate", "object"), access_policy, decision)
    if structured is not None:
        return structured
    return apply_text_redactions(f"{subject} {predicate} {object_value}", access_policy, decision)


def apply_relation_redactions(
    *,
    source: str,
    predicate: str,
    target: str,
    access_policy: Mapping[str, Any] | None,
    decision: AccessDecision,
) -> tuple[str, dict[str, Any]]:
    record = {"source": source, "predicate": predicate, "target": target}
    structured = _apply_structured_record_redactions(record, ("source", "predicate", "target"), access_policy, decision)
    if structured is not None:
        return structured
    return apply_text_redactions(f"{source} {predicate} {target}", access_policy, decision)


def apply_record_redactions(
    record: Mapping[str, Any],
    access_policy: Mapping[str, Any] | None,
    decision: AccessDecision,
    *,
    redactable_keys: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Redact structured export fields while preserving the record envelope."""

    copied = dict(record)
    metadata = _redaction_metadata(decision)
    if not decision.redacted:
        return copied, metadata
    fields = _str_list((access_policy or {}).get("redact_fields"))
    keys = tuple(redactable_keys or copied.keys())
    if not fields:
        placeholder, metadata = _redaction_placeholder((), metadata)
        for key in keys:
            if key in copied:
                copied[key] = placeholder
        return copied, metadata

    structured = _redact_structured_value({key: copied.get(key) for key in keys if key in copied}, fields)
    if structured is None:
        placeholder, metadata = _redaction_placeholder(fields, metadata)
        for key in keys:
            if key in copied:
                copied[key] = placeholder
        return copied, metadata
    redacted_record, structured_metadata = structured
    metadata.update(structured_metadata)
    for key, value in redacted_record.items():
        copied[key] = value
    return copied, metadata


def filter_export_for_context(
    exported: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    policy_max_sensitivity: int,
) -> dict[str, Any]:
    """Return a caller-scoped export with explicit omission/redaction disclosure."""

    tenant_id = str(exported.get("tenant_id") or context.get("tenant_id") or context.get("tenant") or "")
    ctx = dict(context)
    if tenant_id:
        ctx.setdefault("tenant_id", tenant_id)
        ctx.setdefault("tenant", tenant_id)
    omitted: dict[str, int] = {}
    omitted_by_reason: dict[str, dict[str, int]] = {}
    redacted: dict[str, int] = {}

    def omit(collection: str, reason: str = "filtered") -> None:
        omitted[collection] = omitted.get(collection, 0) + 1
        reasons = omitted_by_reason.setdefault(collection, {})
        reasons[reason] = reasons.get(reason, 0) + 1

    def record_redaction(collection: str, privacy: Mapping[str, Any]) -> None:
        if bool(privacy.get("redacted")):
            redacted[collection] = redacted.get(collection, 0) + 1

    evidence_by_cid: dict[str, Mapping[str, Any]] = {
        str(item.get("cid")): item
        for item in exported.get("evidence", [])
        if isinstance(item, Mapping) and item.get("cid")
    }
    allowed_evidence_cids: set[str] = set()

    def source_sensitivity(row: Mapping[str, Any]) -> int:
        sensitivities: list[int] = []
        if row.get("sensitivity") is not None:
            sensitivities.append(_int_or_zero(row.get("sensitivity")))
        for cid in _str_list(row.get("source_evidence_cids")):
            source = evidence_by_cid.get(cid)
            if source is not None:
                sensitivities.append(_int_or_zero(source.get("sensitivity")))
        return max(sensitivities or [0])

    def source_denial_reason(row: Mapping[str, Any]) -> str | None:
        for cid in _str_list(row.get("source_evidence_cids")):
            if cid not in evidence_by_cid:
                return "source_evidence_missing"
            if cid not in allowed_evidence_cids:
                return "source_evidence_denied"
        return None

    def attach_privacy(record: Mapping[str, Any], privacy: Mapping[str, Any]) -> dict[str, Any]:
        copied = dict(record)
        copied["privacy"] = dict(privacy)
        return copied

    def scrub(record: Mapping[str, Any], drop_keys: Sequence[str]) -> dict[str, Any]:
        copied = dict(record)
        for key in drop_keys:
            copied.pop(key, None)
        return copied

    def decision_for(
        row: Mapping[str, Any],
        *,
        sensitivity: int,
        status: str = "active",
        erased: bool = False,
    ) -> AccessDecision:
        return may_read_item(
            item_tenant_id=str(row.get("tenant_id") or tenant_id),
            sensitivity=int(sensitivity),
            access_policy=row.get("access_policy") if isinstance(row.get("access_policy"), Mapping) else {},
            context=ctx,
            policy_max_sensitivity=policy_max_sensitivity,
            status=status,
            erased=erased,
        )

    filtered_evidence: list[dict[str, Any]] = []
    for item in exported.get("evidence", []):
        if not isinstance(item, Mapping):
            omit("evidence", "invalid_record")
            continue
        decision = decision_for(
            item,
            sensitivity=_int_or_zero(item.get("sensitivity")),
            status="active",
            erased=bool(item.get("erased")),
        )
        if not decision.allowed:
            omit("evidence", decision.reason)
            continue
        policy = item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {}
        record = scrub(item, ("access_policy", "embedding"))
        content, privacy = apply_text_redactions(str(record.get("content") or ""), policy, decision)
        record["content"] = content
        if decision.redacted:
            for field in _str_list(policy.get("redact_fields")):
                if field in record and field != "content":
                    record[field] = f"[REDACTED:{field}]"
                    privacy["redacted"] = True
                    privacy["redaction_mode"] = "structured"
        record = attach_privacy(record, privacy)
        record_redaction("evidence", privacy)
        filtered_evidence.append(record)
        if record.get("cid"):
            allowed_evidence_cids.add(str(record["cid"]))

    def filter_assertions() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        allowed_assertion_ids.clear()
        for item in exported.get("assertions", []):
            if not isinstance(item, Mapping):
                omit("assertions", "invalid_record")
                continue
            source_denial = source_denial_reason(item)
            if source_denial:
                omit("assertions", source_denial)
                continue
            decision = decision_for(
                item,
                sensitivity=source_sensitivity(item),
                status=str(item.get("status") or "candidate"),
            )
            if not decision.allowed:
                omit("assertions", decision.reason)
                continue
            text, privacy = apply_statement_redactions(
                subject=str(item.get("subject") or ""),
                predicate=str(item.get("predicate") or ""),
                object_value=str(item.get("object") or ""),
                access_policy=item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {},
                decision=decision,
            )
            record = scrub(
                item,
                (
                    "access_policy",
                    "access_count",
                    "calibration",
                    "justification_id",
                    "last_accessed",
                    "scope",
                    "user_id",
                ),
            )
            redacted_record = privacy.get("redacted_record")
            if isinstance(redacted_record, Mapping):
                record["subject"] = str(redacted_record.get("subject", record.get("subject", "")))
                record["predicate"] = str(redacted_record.get("predicate", record.get("predicate", "")))
                record["object"] = str(redacted_record.get("object", record.get("object", "")))
            elif decision.redacted:
                record["subject"] = text
                record["predicate"] = "[REDACTED]"
                record["object"] = "[REDACTED]"
            record = attach_privacy(record, privacy)
            record_redaction("assertions", privacy)
            rows.append(record)
            if record.get("id"):
                allowed_assertion_ids.add(str(record["id"]))
        return rows

    allowed_assertion_ids: set[str] = set()
    filtered_assertions = filter_assertions()

    def filter_relations() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in exported.get("relations", []):
            if not isinstance(item, Mapping):
                omit("relations", "invalid_record")
                continue
            source_denial = source_denial_reason(item)
            if source_denial:
                omit("relations", source_denial)
                continue
            decision = decision_for(item, sensitivity=source_sensitivity(item), status="active")
            if not decision.allowed:
                omit("relations", decision.reason)
                continue
            text, privacy = apply_relation_redactions(
                source=str(item.get("source") or ""),
                predicate=str(item.get("predicate") or ""),
                target=str(item.get("target") or ""),
                access_policy=item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {},
                decision=decision,
            )
            record = scrub(item, ("access_policy",))
            redacted_record = privacy.get("redacted_record")
            if isinstance(redacted_record, Mapping):
                record["source"] = str(redacted_record.get("source", record.get("source", "")))
                record["predicate"] = str(redacted_record.get("predicate", record.get("predicate", "")))
                record["target"] = str(redacted_record.get("target", record.get("target", "")))
            elif decision.redacted:
                record["source"] = text
                record["predicate"] = "[REDACTED]"
                record["target"] = "[REDACTED]"
            record = attach_privacy(record, privacy)
            record_redaction("relations", privacy)
            rows.append(record)
        return rows

    def filter_preferences() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in exported.get("preferences", []):
            if not isinstance(item, Mapping):
                omit("preferences", "invalid_record")
                continue
            source_denial = source_denial_reason(item)
            if source_denial:
                omit("preferences", source_denial)
                continue
            decision = decision_for(
                item,
                sensitivity=source_sensitivity(item),
                status=str(item.get("status") or "active"),
            )
            if not decision.allowed:
                omit("preferences", decision.reason)
                continue
            statement, privacy = apply_text_redactions(
                str(item.get("statement") or ""),
                item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {},
                decision,
            )
            record = scrub(item, ("access_policy", "exceptions", "scope", "user_id"))
            record["statement"] = statement
            record = attach_privacy(record, privacy)
            record_redaction("preferences", privacy)
            rows.append(record)
        return rows

    def filter_entities() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in exported.get("entities", []):
            if not isinstance(item, Mapping):
                omit("entities", "invalid_record")
                continue
            source_denial = source_denial_reason(item)
            if source_denial:
                omit("entities", source_denial)
                continue
            decision = decision_for(item, sensitivity=source_sensitivity(item), status="active")
            if not decision.allowed:
                omit("entities", decision.reason)
                continue
            record, privacy = apply_record_redactions(
                item,
                item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {},
                decision,
                redactable_keys=("canonical", "type", "summary", "aliases"),
            )
            record = scrub(record, ("access_policy",))
            record = attach_privacy(record, privacy)
            record_redaction("entities", privacy)
            rows.append(record)
        return rows

    filtered_relations = filter_relations()
    filtered_preferences = filter_preferences()
    filtered_entities = filter_entities()
    for item in exported.get("justifications", []):
        if not isinstance(item, Mapping):
            omit("justifications", "invalid_record")
            continue
        omit("justifications", "derived_trace_withheld")

    for item in exported.get("contradictions", []):
        if not isinstance(item, Mapping):
            omit("contradictions", "invalid_record")
            continue
        omit("contradictions", "derived_trace_withheld")

    filtered = {
        "tenant_id": tenant_id,
        "evidence": filtered_evidence,
        "assertions": filtered_assertions,
        "relations": filtered_relations,
        "preferences": filtered_preferences,
        "calibrations": [dict(item) for item in exported.get("calibrations", []) if isinstance(item, Mapping)],
        "entities": filtered_entities,
        "justifications": [],
        "contradictions": [],
        "audit_log": [],
        "deletion_log": [],
        "merge_log": [],
    }
    for log_name in ("audit_log", "deletion_log", "merge_log"):
        for item in exported.get(log_name, []):
            if isinstance(item, Mapping):
                omit(log_name, "raw_log_withheld")

    disclosure = {
        "filtered": True,
        "tenant_id": tenant_id,
        "role": role_for_context(ctx),
        "effective_max_sensitivity": effective_max_sensitivity(ctx, policy_max_sensitivity),
        "omitted": {key: omitted[key] for key in sorted(omitted)},
        "redacted": {key: redacted[key] for key in sorted(redacted)},
        "omitted_by_reason": {
            collection: {reason: reasons[reason] for reason in sorted(reasons)}
            for collection, reasons in sorted(omitted_by_reason.items())
        },
        "logs": "audit_log, deletion_log, and merge_log are withheld from filtered exports; use internal raw export with an approved operator context for custody review.",
    }
    filtered["disclosure"] = disclosure
    return filtered


def merge_access_policies(policies: Sequence[Mapping[str, Any] | None], *, tenant_id: str | None = None) -> dict[str, Any]:
    """Merge source policies in the most restrictive direction."""

    rows = [
        validate_access_policy(item, tenant_id=tenant_id, location="source access_policy")
        for item in policies
        if item
    ]
    if not rows:
        return {"tenant": tenant_id} if tenant_id else {}
    merged: dict[str, Any] = {}
    tenants = {str(row.get("tenant") or row.get("tenant_id") or "") for row in rows if row.get("tenant") or row.get("tenant_id")}
    if tenant_id:
        tenants.add(str(tenant_id))
    if len(tenants) == 1:
        merged["tenant"] = next(iter(tenants))
    elif len(tenants) > 1:
        merged["tenant"] = sorted(tenants)[0]
        merged["restricted"] = True
        merged["hold"] = "tenant-conflict"

    _merge_intersection(merged, rows, "allow_roles")
    _merge_intersection(merged, rows, "allow_principals")
    _merge_intersection(merged, rows, "purpose", aliases=("purposes",))
    _merge_intersection(merged, rows, "residency", aliases=("residencies", "region", "regions"))
    _merge_intersection(merged, rows, "lawful_basis")
    _merge_union(merged, rows, "require_capabilities")
    _merge_union(merged, rows, "redact_fields")

    max_values = [item for row in rows if (item := row.get("max_sensitivity")) is not None]
    if max_values:
        try:
            merged["max_sensitivity"] = min(int(item) for item in max_values)
        except (TypeError, ValueError):
            merged["restricted"] = True
    raw_roles = [str(row.get("min_role_for_raw") or "").lower() for row in rows if row.get("min_role_for_raw")]
    if raw_roles:
        merged["min_role_for_raw"] = max(raw_roles, key=lambda role: ROLE_RANK.get(role, 99))
    expirations = [str(row.get("expires_at")) for row in rows if row.get("expires_at")]
    if expirations:
        merged["expires_at"] = sorted(expirations)[0]
    if any(bool(row.get("restricted")) or bool(row.get("hold")) for row in rows):
        merged["restricted"] = True
    if rows and all(bool(row.get("break_glass")) for row in rows):
        merged["break_glass"] = True
    if any(row.get("embed_ok") is False for row in rows):
        merged["embed_ok"] = False
    data_classes = sorted({str(row.get("data_class")) for row in rows if row.get("data_class")})
    if len(data_classes) == 1:
        merged["data_class"] = data_classes[0]
    elif len(data_classes) > 1:
        merged["data_class"] = "mixed"
    return merged


def _normalise_vector_partition(value: object) -> str | None:
    if value is None:
        return None
    partition = str(value).strip().lower()
    if partition in VECTOR_PARTITIONS:
        return partition
    return VECTOR_PARTITION_NONE


def _raw_vector_restricted(policy: Mapping[str, Any], sensitivity: int) -> bool:
    if sensitivity >= 2:
        return True
    if _str_list(policy.get("redact_fields")):
        return True
    if str(policy.get("min_role_for_raw") or "").strip():
        return True
    data_class = str(policy.get("data_class") or "").strip().lower()
    return data_class in _PRIVATE_VECTOR_DATA_CLASSES


def _redaction_metadata(decision: AccessDecision) -> dict[str, Any]:
    metadata = {
        "access_decision": decision.reason,
        "role": decision.role,
        "effective_max_sensitivity": decision.ceiling,
        "redacted": False,
    }
    if decision.unknown_keys:
        metadata["unknown_access_policy_keys"] = list(decision.unknown_keys)
    return metadata


def _redact_json_text(text: str, fields: Sequence[str]) -> tuple[str, dict[str, Any]] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, (Mapping, list)):
        return None
    structured = _redact_structured_value(parsed, fields)
    if structured is None:
        return _redaction_placeholder(fields, {})
    redacted, metadata = structured
    return json.dumps(redacted, sort_keys=True, separators=(",", ":")), metadata


def _redact_structured_value(value: Any, fields: Sequence[str]) -> tuple[Any, dict[str, Any]] | None:
    normalized_fields = [field for field in fields if field]
    found: set[str] = set()

    def walk(node: Any, path: tuple[str, ...]) -> Any:
        if isinstance(node, Mapping):
            redacted_node: dict[Any, Any] = {}
            for key, child in node.items():
                key_text = str(key).strip().lower()
                child_path = (*path, key_text)
                matching_fields = [
                    field
                    for field in normalized_fields
                    if _field_matches_path(field, child_path)
                ]
                if matching_fields:
                    label = max(matching_fields, key=lambda item: (item.count("."), len(item)))
                    found.update(matching_fields)
                    redacted_node[key] = f"[REDACTED:{label}]"
                else:
                    redacted_node[key] = walk(child, child_path)
            return redacted_node
        if isinstance(node, list):
            return [walk(item, path) for item in node]
        return node

    redacted = walk(value, ())
    missing = sorted(set(normalized_fields) - found)
    if missing:
        return None
    return (
        redacted,
        {
            "redacted": True,
            "redact_fields": list(normalized_fields),
            "redaction_mode": "structured",
            "redacted_field_count": len(found),
        },
    )


def _field_matches_path(field: str, path: tuple[str, ...]) -> bool:
    segments = tuple(part for part in field.split(".") if part)
    if not segments:
        return False
    if len(segments) == 1:
        return bool(path and path[-1] == segments[0])
    return path[-len(segments) :] == segments


def _apply_structured_record_redactions(
    record: Mapping[str, str],
    render_order: Sequence[str],
    access_policy: Mapping[str, Any] | None,
    decision: AccessDecision,
) -> tuple[str, dict[str, Any]] | None:
    fields = _str_list((access_policy or {}).get("redact_fields"))
    metadata = _redaction_metadata(decision)
    if not decision.redacted:
        return " ".join(str(record[key]) for key in render_order), metadata
    if not fields:
        return _redaction_placeholder((), metadata)

    structured = _redact_structured_value(dict(record), fields)
    if structured is None:
        return None
    redacted_record, structured_metadata = structured
    metadata.update(structured_metadata)
    metadata["redacted_record"] = {key: str(redacted_record[key]) for key in render_order}
    return " ".join(str(redacted_record[key]) for key in render_order), metadata


def _redaction_placeholder(fields: Sequence[str], metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    missing = sorted(set(fields))
    metadata.update(
        {
            "redacted": True,
            "redact_fields": list(fields),
            "redaction_mode": "placeholder",
            "missing_redact_fields": missing,
        }
    )
    label = ", ".join(missing) if missing else "unspecified"
    return "[REDACTED fields: " + label + "]", metadata


def _merge_intersection(merged: dict[str, Any], rows: Sequence[dict[str, Any]], key: str, aliases: tuple[str, ...] = ()) -> None:
    values = [_str_set(row.get(key) or next((row.get(alias) for alias in aliases if row.get(alias)), None)) for row in rows]
    present = [value for value in values if value]
    if not present:
        return
    intersection = set.intersection(*present) if len(present) > 1 else set(present[0])
    merged[key] = sorted(intersection)


def _merge_union(merged: dict[str, Any], rows: Sequence[dict[str, Any]], key: str) -> None:
    union: set[str] = set()
    for row in rows:
        union.update(_str_set(row.get(key)))
    if union:
        merged[key] = sorted(union)


def _scope_allows(policy_scope: Any, context_scope: Any) -> bool:
    if policy_scope in (None, "", [], {}, ()):
        return True
    if context_scope in (None, "", [], {}, ()):
        return False
    if isinstance(policy_scope, Mapping):
        if not isinstance(context_scope, Mapping):
            return False
        return all(context_scope.get(key) == value for key, value in policy_scope.items())
    return bool(_str_set(policy_scope) & _str_set(context_scope))


def _residency_allows(policy: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    policy_value = (
        policy.get("residency")
        or policy.get("residencies")
        or policy.get("region")
        or policy.get("regions")
        or policy.get("allowed_residencies")
        or policy.get("runtime_residency")
    )
    policy_set = _str_set(policy_value)
    if not policy_set:
        return True
    context_set = _str_set(context.get("residency") or context.get("runtime_residency") or context.get("region"))
    if not context_set:
        # Existing local ingest rows sometimes carry residency metadata without
        # a runtime residency context; keep that compatibility, but explicit
        # mismatches below remain deny-by-default.
        return True
    if policy_set & context_set:
        return True
    if policy.get("cross_region_transfer") is False:
        return False
    transfer_set = _str_set(policy.get("allowed_residency_transfers"))
    return bool(transfer_set and context_set <= transfer_set)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _intersects_if_policy_set(policy_value: Any, context_value: Any, *, allow_absent_context: bool = False) -> bool:
    policy_set = _str_set(policy_value)
    if not policy_set:
        return True
    context_set = _str_set(context_value)
    if not context_set:
        return allow_absent_context
    return bool(policy_set & context_set)


def _expired(value: Any) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) <= datetime.now(UTC)


def _str_set(value: Any) -> set[str]:
    return set(_str_list(value))


def _str_list(value: Any) -> list[str]:
    if value in (None, "", [], (), set()):
        return []
    if isinstance(value, str):
        return [value.strip().lower()] if value.strip() else []
    if isinstance(value, Mapping):
        return [str(key).strip().lower() for key, enabled in value.items() if enabled and str(key).strip()]
    if isinstance(value, Sequence):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    return [str(value).strip().lower()] if str(value).strip() else []
