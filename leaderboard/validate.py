"""Validate public leaderboard result records."""

import json
import math
import re
import sys
from pathlib import Path
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
    return sorted(set(errors))


def validate_record(record: object) -> list[str]:
    """Return stable JSON-pointer errors; an empty list means valid."""
    if not isinstance(record, dict):
        return ["/"]

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
