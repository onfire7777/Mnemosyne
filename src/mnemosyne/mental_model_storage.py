"""Engine-neutral storage validation for advisory mental-model records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


class MentalModelConflict(ValueError):
    """A create-only operation or optimistic version precondition failed."""


def json_copy(value: Any) -> Any:
    """Accept only finite, plain JSON without coercing keys or Python objects."""
    def check(item: Any, depth: int = 0) -> None:
        if depth > 64:
            raise ValueError("mental model JSON nesting is too deep")
        if item is None or type(item) in {str, bool, int, float}:
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise ValueError("mental model records must contain plain JSON values and string keys")

    check(value)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, OverflowError) as exc:
        raise ValueError("mental model records must contain finite JSON values") from exc


def model_key(tenant_id: str, model_id: str, branch: str) -> tuple[str, str, str]:
    for value in (tenant_id, model_id, branch):
        if type(value) is not str or not value.strip():
            raise ValueError("mental model tenant, model ID and branch must be non-empty strings")
    return tenant_id, branch, model_id


def expected_version(value: int | None, *, allow_create: bool = False) -> None:
    if value is None and allow_create:
        return
    if type(value) is not int or value < 1:
        raise ValueError("expected_version must be a positive integer")


def validate_record(tenant_id: str, model_id: str, record: dict[str, Any], branch: str) -> dict[str, Any]:
    model_key(tenant_id, model_id, branch)
    if type(record) is not dict:
        raise ValueError("mental model record must be a JSON object")
    copied = json_copy(record)
    for field, value in (("tenant_id", tenant_id), ("branch", branch), ("model_id", model_id)):
        if copied.get(field) != value:
            raise ValueError(f"mental model {field} does not match storage scope")
    for field in ("owner_id", "name", "question", "created_at", "updated_at", "status"):
        if type(copied.get(field)) is not str or not copied[field].strip():
            raise ValueError(f"mental model {field} must be a non-empty string")
    if type(copied.get("scope")) is not dict or type(copied.get("revisions")) is not list:
        raise ValueError("mental model scope must be an object and revisions must be a list")
    if "answer" not in copied or "corpus_fingerprint" not in copied:
        raise ValueError("mental model record requires answer and corpus_fingerprint")
    if copied["corpus_fingerprint"] is not None and type(copied["corpus_fingerprint"]) is not str:
        raise ValueError("mental model corpus_fingerprint must be a string or null")
    sources = copied.setdefault("source_evidence_cids", [])
    if type(sources) is not list or any(type(cid) is not str or not cid.strip() for cid in sources):
        raise ValueError("mental model source_evidence_cids must be a list of non-empty strings")
    return copied


def prepare_save(
    tenant_id: str, model_id: str, record: dict[str, Any], branch: str,
    current: dict[str, Any] | None, version: int | None,
) -> dict[str, Any]:
    expected_version(version, allow_create=True)
    copied = validate_record(tenant_id, model_id, record, branch)
    if current is None:
        if version is not None:
            raise MentalModelConflict("mental model version conflict")
        copied["version"] = 1
    else:
        if version is None or current["version"] != version:
            raise MentalModelConflict("mental model version conflict")
        if copied["owner_id"] != current["owner_id"]:
            raise ValueError("mental model owner_id is immutable")
        if copied["created_at"] != current["created_at"]:
            raise ValueError("mental model created_at is immutable")
        copied["version"] = version + 1
    return copied


def invalidate_record(record: dict[str, Any]) -> dict[str, Any]:
    copied = json_copy(record)
    copied.update(answer=None, status="stale", corpus_fingerprint=None, source_evidence_cids=[],
                  version=record["version"] + 1, updated_at=datetime.now(UTC).isoformat())
    return copied
