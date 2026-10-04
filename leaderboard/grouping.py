"""Versioned comparison candidates; no ranking, averaging or publication grant."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re

from leaderboard.validate import SCHEMA_VERSION_V2, validate_record, verify_result_digests

CONTEXT_VERSION = "openmembench.comparison-context/v1"
INDEX_VERSION = "openmembench.comparison-index/v1"
_CONTEXT_FIELDS = (
    "dataset_digest", "protocol_digest", "preprocessing_digest",
    "scorer_digest", "model_policy_digest",
)
_IDENTITY_FIELDS = (
    "track_kind", "benchmark_id", "benchmark_version", "module_id", "division",
    "resource_profile", "model_policy_id", "dataset_split_digest",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON value")


def _context(record: dict, payloads: dict[str, bytes]) -> tuple[dict | None, str | None]:
    if verify_result_digests(record, payloads):
        return None, "unverified-artifacts"
    try:
        config = json.loads(payloads["config.json"], object_pairs_hook=_pairs,
                            parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return None, "invalid-config"
    if not isinstance(config, dict):
        return None, "invalid-config"
    context = config.get("comparison_context")
    if context is None:
        return None, "comparison-context-unavailable"
    if (not isinstance(context, dict)
            or set(context) != {"schema_version", *_CONTEXT_FIELDS}
            or context.get("schema_version") != CONTEXT_VERSION
            or any(not isinstance(context.get(field), str)
                   or not _DIGEST.fullmatch(context[field]) for field in _CONTEXT_FIELDS)):
        return None, "invalid-comparison-context"
    fidelity = record.get("lineage", {}).get("fidelity", {})
    if not isinstance(fidelity, dict):
        return None, "comparison-context-lineage-mismatch"
    # Existing official lineage is authoritative. A new context cannot replace it.
    aliases = {"protocol_digest": "upstream_protocol_digest"}
    for field in _CONTEXT_FIELDS:
        source = aliases.get(field, field)
        if source in fidelity and context[field] != fidelity[source]:
            return None, "comparison-context-lineage-mismatch"
    if "split_digest" in fidelity and fidelity["split_digest"] != record["identity"]["dataset_split_digest"]:
        return None, "comparison-context-lineage-mismatch"
    return context, None


def build_comparison_index(records: list[dict], artifacts: dict[str, dict[str, bytes]]) -> dict:
    """Derive reproducible candidate groups from atomic rows and bound payloads.

    Eligible means compatible for side-by-side inspection, not certified or
    publishable. Every rejected row remains in exclusions with a stable reason.
    """
    ids = [record.get("record_id") for record in records]
    if any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("comparison source IDs must be unique strings")
    ordered = sorted(records, key=lambda record: record["record_id"])
    valid = {record["record_id"]: not validate_record(record) for record in ordered}
    attempts = Counter(
        (r["identity"]["system_id"], r["identity"]["run_id"], r["identity"]["attempt_id"])
        for r in ordered if valid[r["record_id"]] and r["schema_version"] == SCHEMA_VERSION_V2
    )
    groups = {}
    exclusions = []
    for record in ordered:
        record_id = record["record_id"]
        reason = None
        context = None
        if not valid[record_id]:
            reason = "invalid-record"
        elif record["schema_version"] != SCHEMA_VERSION_V2:
            reason = "legacy-comparison-metadata-unavailable"
        else:
            identity = record["identity"]
            if attempts[(identity["system_id"], identity["run_id"], identity["attempt_id"])] != 1:
                reason = "ambiguous-duplicate-attempt"
            elif record["attempt_outcome"] != "measured":
                reason = "attempt-" + record["attempt_outcome"]
            elif any(gate["status"] != "passed" for gate in record["safety_gates"]):
                reason = "safety-gates-not-passed"
            elif record["resources"]["treatment"] != "verified":
                reason = "resources-not-verified"
            else:
                context, reason = _context(record, artifacts.get(record_id, {}))
        if reason:
            exclusions.append({"record_id": record_id, "reason": reason})
            continue
        for metric in record["metrics"]:
            key = {field: identity[field] for field in _IDENTITY_FIELDS}
            key.update({field: context[field] for field in _CONTEXT_FIELDS})
            key["metric"] = {field: metric[field] for field in ("name", "family", "unit")}
            key["resource_treatment"] = record["resources"]["treatment"]
            key["judge"] = metric.get("judge")
            # Efficiency depends directly on hardware/backend. Quality groups
            # disclose those differences in rows instead of hiding other systems.
            if metric["family"] == "performance":
                key.update({field: identity[field] for field in ("hardware_fingerprint", "backend_id")})
            group_id = sha256(_canonical(key)).hexdigest()
            group = groups.setdefault(group_id, {"group_id": group_id, "compatibility": key,
                                                  "source_record_ids": [], "systems": [], "rows": []})
            group["source_record_ids"].append(record_id)
            group["systems"].append(identity["system_id"])
            group["rows"].append({"record_id": record_id, "identity": identity,
                                  "metric": metric, "config_digest": record["config_digest"],
                                  "publication": record["publication"]})
    for group in groups.values():
        group["systems"] = sorted(set(group["systems"]))
        group["multi_system"] = len(group["systems"]) > 1
    return {"schema_version": INDEX_VERSION, "source_digest": "sha256:" + sha256(_canonical(ordered)).hexdigest(),
            "source_record_ids": [r["record_id"] for r in ordered],
            "groups": [groups[key] for key in sorted(groups)], "exclusions": exclusions,
            "compatibility_level": "declared-context",
            "ranking": None, "publication_authorized": False}
