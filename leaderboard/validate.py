"""Validate public leaderboard result records."""

from typing import Any

SCHEMA_VERSION = "mnemosyne.leaderboard.result/v1"
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
_STRING_FIELDS = _REQUIRED_FIELDS[1:11]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_metric(metric: object, index: int) -> list[str]:
    pointer = f"/metrics/{index}"
    if not isinstance(metric, dict):
        return [pointer]

    errors: list[str] = []
    for field in ("name", "family", "unit"):
        if not isinstance(metric.get(field), str) or not metric[field]:
            errors.append(f"{pointer}/{field}")

    family = metric.get("family")
    if family not in {"retrieval", "judged_qa"}:
        errors.append(f"{pointer}/family")
    if not _is_number(metric.get("value")):
        errors.append(f"{pointer}/value")

    interval = metric.get("confidence_interval")
    if not isinstance(interval, dict):
        errors.append(f"{pointer}/confidence_interval")
    else:
        for bound in ("low", "high"):
            if not _is_number(interval.get(bound)):
                errors.append(f"{pointer}/confidence_interval/{bound}")

    if family == "judged_qa":
        judge = metric.get("judge")
        if not isinstance(judge, dict):
            errors.append(f"{pointer}/judge")
        else:
            for field in ("model", "prompt_digest", "config_digest"):
                if not isinstance(judge.get(field), str) or not judge[field]:
                    errors.append(f"{pointer}/judge/{field}")
    elif "judge" in metric:
        errors.append(f"{pointer}/judge")
    return errors


def validate_record(record: object) -> list[str]:
    """Return stable JSON-pointer errors; an empty list means valid."""
    if not isinstance(record, dict):
        return ["/"]

    errors = [f"/{field}" for field in _REQUIRED_FIELDS if field not in record]
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("/schema_version")
    for field in _STRING_FIELDS:
        if field in record and (
            not isinstance(record[field], str) or not record[field]
        ):
            errors.append(f"/{field}")

    metrics: Any = record.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        if "metrics" in record:
            errors.append("/metrics")
    else:
        for index, metric in enumerate(metrics):
            errors.extend(_validate_metric(metric, index))

    for field in ("publication", "operator_entry", "history"):
        value = record.get(field)
        if field in record and (not isinstance(value, dict) or not value):
            errors.append(f"/{field}")
    return sorted(set(errors))
