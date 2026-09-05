"""Validate public leaderboard result records."""

import json
import math
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "mnemosyne.leaderboard.result/v1"
SCHEMA_VERSION_V2 = "mnemosyne.leaderboard.result/v2"
DIGEST_PAYLOAD_NAMES = {
    "build_fingerprint": "build.json",
    "config_digest": "config.json",
    "bundle_digest": "bundle-manifest.json",
    "trace_index_digest": "traces.jsonl",
}
_REQUIRED_FIELDS = (
    "schema_version",
    "record_id",
    "system",
    "track",
    "benchmark",
    "benchmark_version",
    "run_commit",
    "build_fingerprint",
    "config_digest",
    "bundle_digest",
    "trace_index_digest",
    "metrics",
    "publication",
    "operator_entry",
    "history",
)
_STRING_FIELDS = (
    "record_id",
    "system",
    "track",
    "benchmark",
    "benchmark_version",
    "run_commit",
    "build_fingerprint",
    "config_digest",
    "bundle_digest",
    "trace_index_digest",
)
_PUBLICATION_LABELS = ("operator-run", "neutral")
_MAX_JSON_DEPTH = 1_000
_METRIC_FAMILIES = (
    "retrieval",
    "judged_qa",
    "security",
    "calibration",
    "performance",
    "reproducibility",
)
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_DIGEST_FIELDS = (
    "build_fingerprint",
    "config_digest",
    "bundle_digest",
    "trace_index_digest",
)
_V2_REQUIRED_FIELDS = _REQUIRED_FIELDS + (
    "module_id",
    "admission_state",
    "evidence_level",
    "track_kind",
    "lineage",
    "identity",
    "division",
    "capability",
    "safety_gates",
    "resources",
    "run_profile",
    "custody",
    "signer_role",
    "trace_id",
    "attempt_outcome",
)
_ADMISSION_STATES = (
    "PROPOSED",
    "CONTRACT-READY",
    "PILOT-READY-DEV",
    "RUN-READY-OFFICIAL-LOCAL",
    "RUN-READY-HOSTED-X",
    "RUN-READY-P32-OPS",
    "DEFERRED",
    "DEFERRED-CONFLICT",
    "UNSUPPORTED-BY-SYSTEM",
    "REJECTED",
)
_EVIDENCE_LEVELS = (
    "DESIGN_ONLY",
    "IMPLEMENTED",
    "INTERNALLY_MEASURED",
    "PUBLICLY_MEASURED",
)
_TRACK_KINDS = ("OFFICIAL-UPSTREAM", "ENHANCED-SUCCESSOR", "DEVELOPMENT")
_DIVISIONS = (
    "COMPONENT-CLOSED",
    "AGENT-CLOSED",
    "SYSTEM-OPEN",
    "HOSTED-OUTCOME",
)
_CAPABILITIES = ("native", "emulated", "unsupported")
_CUSTODY_LABELS = (
    "development-public",
    "operator-held-out",
    "certification-held-out",
)
_SIGNER_ROLES = ("operator", "independent", "custodian")
_ATTEMPT_OUTCOMES = (
    "measured",
    "missing",
    "unsupported",
    "failed",
    "aborted",
    "not-measured",
)
_RESOURCE_TREATMENTS = ("verified", "resource-unverified")
_SAFETY_STATUSES = ("passed", "failed", "not-measured")
_IDENTITY_FIELDS = (
    "system_id",
    "system_version",
    "adapter_id",
    "adapter_version",
    "track_kind",
    "benchmark_id",
    "benchmark_version",
    "module_id",
    "division",
    "resource_profile",
    "backend_id",
    "hardware_fingerprint",
    "model_policy_id",
    "dataset_split_digest",
    "run_id",
    "attempt_id",
    "seed",
)
_IDENTITY_DIGEST_FIELDS = ("hardware_fingerprint", "dataset_split_digest")
_FIDELITY_FIELDS = (
    "upstream_protocol_digest",
    "dataset_digest",
    "split_digest",
    "preprocessing_digest",
    "scorer_digest",
    "environment_digest",
    "revision_digest",
)
_SUCCESSOR_FIELDS = (
    "parent_official_record_id",
    "parent_construct_digest",
    "difference_manifest_digest",
)
_PROJECTION_VERSION = "mnemosyne.leaderboard.projection/v1"
_PROJECTION_REQUIRED_FIELDS = (
    "schema_version",
    "projection_id",
    "kind",
    "source_record_ids",
    "filters",
    "compatibility_key",
    "exclusions",
    "numerator",
    "denominator",
    "uncertainty_method",
    "missing_count",
    "unsupported_count",
    "failed_count",
    "aborted_count",
    "not_measured_count",
    "certified",
    "official",
    "headline",
    "safety_failures_visible",
)
_OUTCOME_COUNT_FIELDS = {
    "missing": "missing_count",
    "unsupported": "unsupported_count",
    "failed": "failed_count",
    "aborted": "aborted_count",
    "not-measured": "not_measured_count",
}


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _json_nesting_too_deep(raw: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for character in raw:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                return True
        elif character in "]}":
            depth -= 1
    return False


def _unexpected_keys(
    value: dict[str, object], allowed: tuple[str, ...], pointer: str
) -> list[str]:
    return [
        f"{pointer}/{_pointer_token(field)}" for field in value if field not in allowed
    ]


def _pointer_token(value: str) -> str:
    escaped = value.replace("~", "~0").replace("/", "~1")
    return json.dumps(escaped, ensure_ascii=False)[1:-1]


def _validate_metric(metric: object, index: int) -> list[str]:
    pointer = f"/metrics/{index}"
    if not isinstance(metric, dict):
        return [pointer]

    errors = _unexpected_keys(
        metric,
        ("name", "family", "value", "unit", "confidence_interval", "judge"),
        pointer,
    )
    for field in ("name", "family", "unit"):
        if not isinstance(metric.get(field), str) or not metric[field].strip():
            errors.append(f"{pointer}/{field}")

    family = metric.get("family")
    if not isinstance(family, str) or family not in _METRIC_FAMILIES:
        errors.append(f"{pointer}/family")
    if not _is_number(metric.get("value")):
        errors.append(f"{pointer}/value")

    interval = metric.get("confidence_interval")
    if not isinstance(interval, dict):
        errors.append(f"{pointer}/confidence_interval")
    else:
        errors.extend(
            _unexpected_keys(
                interval, ("low", "high"), f"{pointer}/confidence_interval"
            )
        )
        for bound in ("low", "high"):
            if not _is_number(interval.get(bound)):
                errors.append(f"{pointer}/confidence_interval/{bound}")
        low = interval.get("low")
        high = interval.get("high")
        if _is_number(low) and _is_number(high) and low > high:
            errors.append(f"{pointer}/confidence_interval")

    if family == "judged_qa":
        judge = metric.get("judge")
        if not isinstance(judge, dict):
            errors.append(f"{pointer}/judge")
        else:
            errors.extend(
                _unexpected_keys(
                    judge,
                    ("model", "prompt_digest", "config_digest"),
                    f"{pointer}/judge",
                )
            )
            for field in ("model", "prompt_digest", "config_digest"):
                if not isinstance(judge.get(field), str) or not judge[field].strip():
                    errors.append(f"{pointer}/judge/{field}")
            for field in ("prompt_digest", "config_digest"):
                value = judge.get(field)
                if isinstance(value, str) and not _SHA256.fullmatch(value):
                    errors.append(f"{pointer}/judge/{field}")
    elif "judge" in metric:
        errors.append(f"{pointer}/judge")
    return errors


def _validate_publication(record: dict[str, object]) -> list[str]:
    publication = record.get("publication")
    if not isinstance(publication, dict):
        return []

    errors = _unexpected_keys(
        publication,
        ("publishable", "label", "register_b_satisfied"),
        "/publication",
    )
    publishable = publication.get("publishable")
    if not isinstance(publishable, bool):
        errors.append("/publication/publishable")
    label = publication.get("label")
    if not isinstance(label, str) or label not in _PUBLICATION_LABELS:
        errors.append("/publication/label")
    if record.get("track") == "development" and publishable is True:
        errors.append("/publication/publishable")
    if "register_b_satisfied" in publication and not isinstance(
        publication["register_b_satisfied"], bool
    ):
        errors.append("/publication/register_b_satisfied")
    if label == "neutral" and (publication.get("register_b_satisfied") is not True):
        errors.append("/publication/register_b_satisfied")
    return errors


def _validate_history(record: dict[str, object]) -> list[str]:
    history = record.get("history")
    if not isinstance(history, dict):
        return []
    errors = _unexpected_keys(history, ("supersedes",), "/history")
    if "supersedes" not in history:
        return errors + ["/history/supersedes"]

    supersedes = history["supersedes"]
    if supersedes is not None and (
        not isinstance(supersedes, str) or not supersedes.strip()
    ):
        errors.append("/history/supersedes")
    if supersedes == record.get("record_id"):
        errors.append("/record_id")
    return errors


def _validate_records(records: list[object]) -> list[str]:
    errors: list[str] = []
    indexes: dict[str, int] = {}
    links: dict[str, str] = {}
    all_ids = {
        item.get("record_id")
        for item in records
        if isinstance(item, dict) and isinstance(item.get("record_id"), str)
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            continue
        if record_id in indexes:
            errors.append(f"/{index}/record_id")
            continue
        indexes[record_id] = index
        history = record.get("history")
        if isinstance(history, dict):
            supersedes = history.get("supersedes")
            if isinstance(supersedes, str) and supersedes in all_ids:
                links[record_id] = supersedes

    cyclic: set[str] = set()
    resolved: set[str] = set()
    for start in links:
        if start in resolved:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        current = start
        while current in links and current not in positions and current not in resolved:
            positions[current] = len(path)
            path.append(current)
            current = links[current]
        if current in positions:
            cyclic.update(path[positions[current] :])
        resolved.update(path)
    errors.extend(f"/{indexes[record_id]}/history/supersedes" for record_id in cyclic)

    identities: dict[tuple[object, ...], int] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if record.get("schema_version") != SCHEMA_VERSION_V2:
            continue
        identity = record.get("identity")
        key = _identity_key(identity)
        if key is None:
            continue
        if key in identities:
            errors.append(f"/{index}/identity")
        else:
            identities[key] = index
    return sorted(set(errors))


def _identity_key(identity: object) -> tuple[object, ...] | None:
    if not isinstance(identity, dict):
        return None
    key: list[object] = []
    for field in _IDENTITY_FIELDS:
        value = identity.get(field)
        if value is None:
            return None
        key.append(value)
    return tuple(key)


def validate_record(record: object) -> list[str]:
    """Return stable JSON-pointer errors; an empty list means valid."""
    if not isinstance(record, dict):
        return ["/"]
    if record.get("schema_version") == SCHEMA_VERSION_V2:
        return _validate_record_v2(record)
    return _validate_record_v1(record)


def _validate_record_v1(record: dict[str, object]) -> list[str]:
    errors = _unexpected_keys(record, _REQUIRED_FIELDS, "")
    errors.extend(f"/{field}" for field in _REQUIRED_FIELDS if field not in record)
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("/schema_version")
    for field in _STRING_FIELDS:
        if field in record and (
            not isinstance(record[field], str) or not record[field].strip()
        ):
            errors.append(f"/{field}")
    run_commit = record.get("run_commit")
    if isinstance(run_commit, str) and not _COMMIT.fullmatch(run_commit):
        errors.append("/run_commit")
    for field in _DIGEST_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and not _SHA256.fullmatch(value):
            errors.append(f"/{field}")

    metrics: Any = record.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        if "metrics" in record:
            errors.append("/metrics")
    else:
        families: set[object] = set()
        for index, metric in enumerate(metrics):
            errors.extend(_validate_metric(metric, index))
            if isinstance(metric, dict):
                family = metric.get("family")
                if family in _METRIC_FAMILIES:
                    families.add(family)
        if len(families) > 1:
            errors.append("/metrics")

    for field in ("publication", "operator_entry", "history"):
        value = record.get(field)
        if field in record and (not isinstance(value, dict) or not value):
            errors.append(f"/{field}")
    operator_entry = record.get("operator_entry")
    if isinstance(operator_entry, dict):
        errors.extend(
            _unexpected_keys(
                operator_entry, ("operator", "disclosed"), "/operator_entry"
            )
        )
        operator = operator_entry.get("operator")
        if not isinstance(operator, str) or not operator.strip():
            errors.append("/operator_entry/operator")
        if operator_entry.get("disclosed") is not True:
            errors.append("/operator_entry/disclosed")
    errors.extend(_validate_publication(record))
    errors.extend(_validate_history(record))
    return sorted(set(errors))


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_enum(
    record: dict[str, object], field: str, allowed: tuple[str, ...]
) -> list[str]:
    value = record.get(field)
    if not isinstance(value, str) or value not in allowed:
        return [f"/{field}"]
    return []


def _validate_publication_v2(record: dict[str, object]) -> list[str]:
    publication = record.get("publication")
    if not isinstance(publication, dict):
        return []
    errors = _unexpected_keys(
        publication,
        ("publishable", "label", "register_b_satisfied", "pbpp_headline_eligible"),
        "/publication",
    )
    publishable = publication.get("publishable")
    if not isinstance(publishable, bool):
        errors.append("/publication/publishable")
    label = publication.get("label")
    if not isinstance(label, str) or label not in _PUBLICATION_LABELS:
        errors.append("/publication/label")
    development = (
        record.get("track") == "development"
        or record.get("track_kind") == "DEVELOPMENT"
    )
    if development and publishable is True:
        errors.append("/publication/publishable")
    headline = publication.get("pbpp_headline_eligible")
    if not isinstance(headline, bool):
        errors.append("/publication/pbpp_headline_eligible")
    elif headline is True and (
        development
        or label != "neutral"
        or publication.get("register_b_satisfied") is not True
    ):
        errors.append("/publication/pbpp_headline_eligible")
    if "register_b_satisfied" in publication and not isinstance(
        publication["register_b_satisfied"], bool
    ):
        errors.append("/publication/register_b_satisfied")
    if label == "neutral" and publication.get("register_b_satisfied") is not True:
        errors.append("/publication/register_b_satisfied")
    return errors


def _validate_identity(record: dict[str, object]) -> list[str]:
    identity = record.get("identity")
    if not isinstance(identity, dict):
        return []
    errors = _unexpected_keys(identity, _IDENTITY_FIELDS, "/identity")
    for field in _IDENTITY_FIELDS:
        if field not in identity:
            errors.append(f"/identity/{field}")
    for field in _IDENTITY_FIELDS:
        if field == "seed":
            continue
        if field in identity and not _nonempty_string(identity.get(field)):
            errors.append(f"/identity/{field}")
    seed = identity.get("seed")
    if "seed" in identity and type(seed) is not int:
        errors.append("/identity/seed")
    for field in _IDENTITY_DIGEST_FIELDS:
        value = identity.get(field)
        if isinstance(value, str) and not _SHA256.fullmatch(value):
            errors.append(f"/identity/{field}")
    if (
        isinstance(identity.get("track_kind"), str)
        and identity.get("track_kind") != record.get("track_kind")
    ):
        errors.append("/identity/track_kind")
    if (
        isinstance(identity.get("division"), str)
        and identity.get("division") != record.get("division")
    ):
        errors.append("/identity/division")
    if (
        isinstance(identity.get("module_id"), str)
        and identity.get("module_id") != record.get("module_id")
    ):
        errors.append("/identity/module_id")
    return errors


def _validate_lineage(record: dict[str, object]) -> list[str]:
    lineage = record.get("lineage")
    if not isinstance(lineage, dict):
        return []
    track_kind = record.get("track_kind")
    if track_kind == "DEVELOPMENT":
        return _unexpected_keys(lineage, (), "/lineage")
    if track_kind == "OFFICIAL-UPSTREAM":
        errors = _unexpected_keys(lineage, ("fidelity",), "/lineage")
        fidelity = lineage.get("fidelity")
        if not isinstance(fidelity, dict):
            errors.append("/lineage/fidelity")
            return errors
        errors.extend(_unexpected_keys(fidelity, _FIDELITY_FIELDS, "/lineage/fidelity"))
        for field in _FIDELITY_FIELDS:
            value = fidelity.get(field)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                errors.append(f"/lineage/fidelity/{field}")
        return errors
    if track_kind == "ENHANCED-SUCCESSOR":
        errors = _unexpected_keys(lineage, _SUCCESSOR_FIELDS, "/lineage")
        parent = lineage.get("parent_official_record_id")
        if not _nonempty_string(parent):
            errors.append("/lineage/parent_official_record_id")
        for field in ("parent_construct_digest", "difference_manifest_digest"):
            value = lineage.get(field)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                errors.append(f"/lineage/{field}")
        return errors
    return []


def _validate_safety_gates(record: dict[str, object]) -> list[str]:
    gates = record.get("safety_gates")
    if not isinstance(gates, list) or not gates:
        return ["/safety_gates"] if "safety_gates" in record else []
    errors: list[str] = []
    for index, gate in enumerate(gates):
        pointer = f"/safety_gates/{index}"
        if not isinstance(gate, dict):
            errors.append(pointer)
            continue
        errors.extend(_unexpected_keys(gate, ("name", "status"), pointer))
        if not _nonempty_string(gate.get("name")):
            errors.append(f"{pointer}/name")
        if gate.get("status") not in _SAFETY_STATUSES:
            errors.append(f"{pointer}/status")
    return errors


def _validate_resources(record: dict[str, object]) -> list[str]:
    resources = record.get("resources")
    if not isinstance(resources, dict):
        return []
    allowed = (
        "treatment",
        "wall_time_ms",
        "peak_rss_bytes",
        "cost",
        "latency_ms",
    )
    errors = _unexpected_keys(resources, allowed, "/resources")
    if resources.get("treatment") not in _RESOURCE_TREATMENTS:
        errors.append("/resources/treatment")
    for field in ("wall_time_ms", "peak_rss_bytes", "cost", "latency_ms"):
        if field in resources and not _is_number(resources[field]):
            errors.append(f"/resources/{field}")
    return errors


def _validate_run_profile(record: dict[str, object]) -> list[str]:
    profile = record.get("run_profile")
    if not isinstance(profile, dict):
        return []
    errors = _unexpected_keys(
        profile, ("profile_id", "seeds", "retries", "aborts"), "/run_profile"
    )
    if not _nonempty_string(profile.get("profile_id")):
        errors.append("/run_profile/profile_id")
    seeds = profile.get("seeds")
    if not isinstance(seeds, list) or any(type(seed) is not int for seed in seeds):
        errors.append("/run_profile/seeds")
    for field in ("retries", "aborts"):
        if type(profile.get(field)) is not int or profile[field] < 0:
            errors.append(f"/run_profile/{field}")
    return errors


def _validate_record_v2(record: dict[str, object]) -> list[str]:
    errors = _unexpected_keys(record, _V2_REQUIRED_FIELDS, "")
    errors.extend(f"/{field}" for field in _V2_REQUIRED_FIELDS if field not in record)
    if record.get("schema_version") != SCHEMA_VERSION_V2:
        errors.append("/schema_version")
    for field in _STRING_FIELDS + ("module_id", "trace_id"):
        if field in record and not _nonempty_string(record.get(field)):
            errors.append(f"/{field}")
    run_commit = record.get("run_commit")
    if isinstance(run_commit, str) and not _COMMIT.fullmatch(run_commit):
        errors.append("/run_commit")
    for field in _DIGEST_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and not _SHA256.fullmatch(value):
            errors.append(f"/{field}")

    metrics: Any = record.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        if "metrics" in record:
            errors.append("/metrics")
    else:
        families: set[object] = set()
        for index, metric in enumerate(metrics):
            errors.extend(_validate_metric(metric, index))
            if isinstance(metric, dict):
                family = metric.get("family")
                if family in _METRIC_FAMILIES:
                    families.add(family)
        if len(families) > 1:
            errors.append("/metrics")

    for field in ("publication", "operator_entry", "history", "lineage", "identity", "resources", "run_profile"):
        value = record.get(field)
        if field in record and field != "lineage" and (not isinstance(value, dict) or not value):
            errors.append(f"/{field}")
        elif field == "lineage" and field in record and not isinstance(value, dict):
            errors.append("/lineage")
    operator_entry = record.get("operator_entry")
    if isinstance(operator_entry, dict):
        errors.extend(
            _unexpected_keys(
                operator_entry, ("operator", "disclosed"), "/operator_entry"
            )
        )
        operator = operator_entry.get("operator")
        if not _nonempty_string(operator):
            errors.append("/operator_entry/operator")
        if operator_entry.get("disclosed") is not True:
            errors.append("/operator_entry/disclosed")
    errors.extend(_validate_enum(record, "admission_state", _ADMISSION_STATES))
    errors.extend(_validate_enum(record, "evidence_level", _EVIDENCE_LEVELS))
    admission = record.get("admission_state")
    if (
        isinstance(admission, str)
        and admission.startswith("RUN-READY-")
        and record.get("evidence_level") != "PUBLICLY_MEASURED"
    ):
        errors.append("/admission_state")
    errors.extend(_validate_enum(record, "track_kind", _TRACK_KINDS))
    errors.extend(_validate_enum(record, "division", _DIVISIONS))
    errors.extend(_validate_enum(record, "capability", _CAPABILITIES))
    errors.extend(_validate_enum(record, "custody", _CUSTODY_LABELS))
    errors.extend(_validate_enum(record, "signer_role", _SIGNER_ROLES))
    errors.extend(_validate_enum(record, "attempt_outcome", _ATTEMPT_OUTCOMES))
    errors.extend(_validate_publication_v2(record))
    errors.extend(_validate_history(record))
    errors.extend(_validate_identity(record))
    errors.extend(_validate_lineage(record))
    errors.extend(_validate_safety_gates(record))
    errors.extend(_validate_resources(record))
    errors.extend(_validate_run_profile(record))
    return sorted(set(errors))


def verify_result_digests(
    record: dict[str, object], artifacts: dict[str, bytes]
) -> list[str]:
    """Hash the named payload bytes; do not parse or reserialize them."""
    errors: list[str] = []
    for field, name in DIGEST_PAYLOAD_NAMES.items():
        payload = artifacts.get(name)
        if payload is None:
            errors.append(f"/{field}")
            continue
        actual = "sha256:" + sha256(payload).hexdigest()
        if record.get(field) != actual:
            errors.append(f"/{field}")
    return sorted(set(errors))


def _source_records(
    projection: dict[str, object], records: list[object]
) -> list[dict[str, object]]:
    wanted = projection.get("source_record_ids")
    if not isinstance(wanted, list):
        return []
    by_id = {
        item.get("record_id"): item
        for item in records
        if isinstance(item, dict) and isinstance(item.get("record_id"), str)
    }
    sources: list[dict[str, object]] = []
    for record_id in wanted:
        item = by_id.get(record_id)
        if isinstance(item, dict):
            sources.append(item)
    return sources


def _has_failed_safety(record: dict[str, object]) -> bool:
    gates = record.get("safety_gates")
    if not isinstance(gates, list):
        return False
    return any(
        isinstance(gate, dict) and gate.get("status") == "failed" for gate in gates
    )


def _outcome_counts(sources: list[dict[str, object]]) -> dict[str, int]:
    counts = {field: 0 for field in _OUTCOME_COUNT_FIELDS.values()}
    for record in sources:
        outcome = record.get("attempt_outcome")
        field = _OUTCOME_COUNT_FIELDS.get(str(outcome))
        if field is not None:
            counts[field] += 1
        if _has_failed_safety(record) and outcome != "failed":
            counts["failed_count"] += 1
    return counts


def _lineage_scorer_digest(record: dict[str, object]) -> str | None:
    lineage = record.get("lineage")
    if not isinstance(lineage, dict):
        return None
    fidelity = lineage.get("fidelity")
    if not isinstance(fidelity, dict):
        return None
    digest = fidelity.get("scorer_digest")
    return digest if isinstance(digest, str) else None


def _identity_value(record: dict[str, object], field: str) -> object:
    identity = record.get("identity")
    if not isinstance(identity, dict):
        return None
    return identity.get(field)


def validate_projection(projection: object, records: list[object]) -> list[str]:
    """Return stable JSON-pointer errors for one derived projection."""
    if not isinstance(projection, dict):
        return ["/"]
    errors: list[str] = []
    for field in _PROJECTION_REQUIRED_FIELDS:
        if field not in projection:
            errors.append(f"/{field}")
    if projection.get("schema_version") != _PROJECTION_VERSION:
        errors.append("/schema_version")
    if projection.get("kind") != "exploratory":
        errors.append("/kind")
    if projection.get("certified") is not False:
        errors.append("/certified")
    if projection.get("official") is not False:
        errors.append("/official")
    if projection.get("headline") is not False:
        errors.append("/headline")
    sources = _source_records(projection, records)
    source_ids = projection.get("source_record_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or len(sources) != len(source_ids)
    ):
        errors.append("/source_record_ids")
    expected = _outcome_counts(sources)
    for field, value in expected.items():
        if projection.get(field) != value:
            errors.append(f"/{field}")
    failed_visible = any(
        _has_failed_safety(record) or record.get("attempt_outcome") == "failed"
        for record in sources
    )
    if failed_visible and projection.get("safety_failures_visible") is not True:
        errors.append("/safety_failures_visible")
    weighting = projection.get("weighting")
    if failed_visible and weighting is not None:
        errors.append("/weighting")
    compatibility = projection.get("compatibility_key")
    if isinstance(compatibility, dict) and sources:
        track = compatibility.get("track_kind")
        if isinstance(track, str) and any(
            record.get("track_kind") != track for record in sources
        ):
            errors.append("/compatibility_key/track_kind")
        division = compatibility.get("division")
        if isinstance(division, str) and any(
            record.get("division") != division for record in sources
        ):
            errors.append("/compatibility_key/division")
        treatment = compatibility.get("resource_treatment")
        if isinstance(treatment, str) and any(
            not isinstance(record.get("resources"), dict)
            or record["resources"].get("treatment") != treatment
            for record in sources
        ):
            errors.append("/compatibility_key/resource_treatment")
        benchmark_id = compatibility.get("benchmark_id")
        if isinstance(benchmark_id, str) and any(
            record.get("benchmark") != benchmark_id
            or _identity_value(record, "benchmark_id") not in {None, benchmark_id}
            for record in sources
        ):
            errors.append("/compatibility_key/benchmark_id")
        benchmark_version = compatibility.get("benchmark_version")
        if isinstance(benchmark_version, str) and any(
            record.get("benchmark_version") != benchmark_version
            or _identity_value(record, "benchmark_version")
            not in {None, benchmark_version}
            for record in sources
        ):
            errors.append("/compatibility_key/benchmark_version")
        scorer = compatibility.get("scorer_digest")
        if isinstance(scorer, str) and any(
            actual is not None and actual != scorer
            for actual in (_lineage_scorer_digest(record) for record in sources)
        ):
            errors.append("/compatibility_key/scorer_digest")
        metric = compatibility.get("metric")
        if isinstance(metric, dict):
            for record in sources:
                metrics = record.get("metrics")
                if not isinstance(metrics, list) or not any(
                    isinstance(item, dict)
                    and item.get("name") == metric.get("name")
                    and item.get("family") == metric.get("family")
                    and item.get("unit") == metric.get("unit")
                    for item in metrics
                ):
                    errors.append("/compatibility_key/metric")
                    break
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    """Validate one record or an array; print errors to stderr; return 0/1/2."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: validate.py RECORD.json", file=sys.stderr)
        return 2

    path = Path(args[0])
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        print(f"error: cannot read JSON: {path}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"error: invalid JSON: {path}", file=sys.stderr)
        return 2
    if _json_nesting_too_deep(raw):
        print(f"error: invalid JSON: {path}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(
            raw,
            parse_constant=_reject_json_constant,
            parse_float=_parse_finite_float,
        )
    except (json.JSONDecodeError, RecursionError, ValueError):
        print(f"error: invalid JSON: {path}", file=sys.stderr)
        return 2

    errors: list[str] = []
    if isinstance(payload, list):
        for index, record in enumerate(payload):
            errors.extend(
                f"/{index}{error}" if error != "/" else f"/{index}"
                for error in validate_record(record)
            )
        errors.extend(_validate_records(payload))
    else:
        errors = validate_record(payload)

    if errors:
        print(*sorted(set(errors)), sep="\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
