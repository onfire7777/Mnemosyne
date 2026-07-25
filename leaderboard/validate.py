"""Validate public leaderboard result records."""

import json
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
_STRING_FIELDS = _REQUIRED_FIELDS[1:11]
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_DIGEST_FIELDS = (
    "build_fingerprint",
    "config_digest",
    "bundle_digest",
    "trace_index_digest",
)


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

    errors: list[str] = []
    publishable = publication.get("publishable")
    if not isinstance(publishable, bool):
        errors.append("/publication/publishable")
    if record.get("track") == "development" and publishable is True:
        errors.append("/publication/publishable")
    if publication.get("label") == "neutral" and (
        publication.get("register_b_satisfied") is not True
    ):
        errors.append("/publication/register_b_satisfied")
    return errors


def _validate_history(record: dict[str, object]) -> list[str]:
    history = record.get("history")
    if not isinstance(history, dict):
        return []
    if "supersedes" not in history:
        return ["/history/supersedes"]

    supersedes = history["supersedes"]
    if supersedes is not None and (
        not isinstance(supersedes, str) or not supersedes
    ):
        return ["/history/supersedes"]
    if supersedes == record.get("record_id"):
        return ["/record_id"]
    return []


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
                families.add(metric.get("family"))
        if {"retrieval", "judged_qa"} <= families:
            errors.append("/metrics")

    for field in ("publication", "operator_entry", "history"):
        value = record.get(field)
        if field in record and (not isinstance(value, dict) or not value):
            errors.append(f"/{field}")
    operator_entry = record.get("operator_entry")
    if isinstance(operator_entry, dict) and (
        operator_entry.get("disclosed") is not True
    ):
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
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"error: invalid JSON: {path}", file=sys.stderr)
        return 2

    errors: list[str] = []
    if isinstance(payload, list):
        for index, record in enumerate(payload):
            errors.extend(
                f"/{index}{error}" if error != "/" else f"/{index}"
                for error in validate_record(record)
            )
    else:
        errors = validate_record(payload)

    if errors:
        print(*sorted(set(errors)), sep="\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
