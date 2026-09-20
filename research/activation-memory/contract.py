"""External JSON contract for reduced activation-memory observations.

This module validates licensed, redacted, scorer-owned DEVELOPMENT receipts
emitted by separately pinned collectors. It does not import model libraries,
store raw activations, or expose a product write path.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PRODUCT_WRITE_PATH = False
MODEL_IMPORT_PATH = False
SCHEMA_ID = "activation-memory-development/observations/0.1"
TRACK = "DEVELOPMENT"
SPLIT_ROLE = "development"
LICENSE = "CC0-1.0"
SUT_BOUNDARY = "external-collector-json"
ABORT_STATUSES = frozenset({"aborted", "completed", "failed"})
OBSERVATION_FAMILIES = frozenset({"j_lens", "persona_drift"})
HEX64 = frozenset("0123456789abcdef")
DEVELOPMENT_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "development.json"
)

_BUNDLE_KEYS = frozenset(
    {
        "abort",
        "custody",
        "headline_eligible",
        "identity",
        "labels",
        "license",
        "model_import_path",
        "observations",
        "product_write_path",
        "publishable",
        "resources",
        "schema_id",
        "split_role",
        "track",
    }
)
_CUSTODY_KEYS = frozenset(
    {
        "authored_from_scratch",
        "class",
        "consent",
        "protected_cases_included",
        "raw_activations_retained",
        "raw_prompts_retained",
        "redacted",
        "upstream_bytes_included",
    }
)
_IDENTITY_KEYS = frozenset(
    {
        "candidate_sha",
        "collector_code_digest",
        "collector_config_digest",
        "collector_license",
        "decoding_digest",
        "hardware_profile",
        "hook_layer",
        "model_content_digest",
        "model_license",
        "model_revision",
        "prompt_corpus_digest",
        "raw_artifact_digest",
        "seed",
        "sut_boundary",
        "tokenizer_digest",
    }
)
_RESOURCE_KEYS = (
    "case_limit",
    "cost_limit_usd",
    "disk_limit_mb",
    "memory_limit_mb",
    "network_limit_bytes",
    "retry_limit",
    "time_limit_s",
    "token_limit",
    "vram_limit_mb",
)
_ABORT_KEYS = frozenset({"reason", "status"})
_OBSERVATION_KEYS = frozenset(
    {"case_id", "content_digest", "family", "redacted", "value"}
)
_LABEL_KEYS = frozenset({"case_id", "expected_tripwire", "family", "owner"})
_DIGEST_FIELDS = frozenset(
    {
        "collector_code_digest",
        "collector_config_digest",
        "decoding_digest",
        "model_content_digest",
        "prompt_corpus_digest",
        "raw_artifact_digest",
        "tokenizer_digest",
    }
)


class ActivationMemoryContractError(ValueError):
    """The observation bundle violated the external JSON contract."""


def load_development_fixture() -> dict[str, Any]:
    payload = json.loads(DEVELOPMENT_FIXTURE_PATH.read_text(encoding="utf-8"))
    return validate_observation_bundle(payload)


def validate_observation_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    bundle = dict(_closed(payload, _BUNDLE_KEYS, "bundle"))
    _require(bundle["schema_id"] == SCHEMA_ID, "schema_id must remain frozen")
    _require(bundle["track"] == TRACK, "track must remain DEVELOPMENT")
    _require(bundle["split_role"] == SPLIT_ROLE, "split_role must remain development")
    _require(bundle["license"] == LICENSE, "license must remain CC0-1.0")
    _require(bundle["publishable"] is False, "bundle must not be publishable")
    _require(bundle["headline_eligible"] is False, "bundle must not be headline eligible")
    _require(
        bundle["product_write_path"] is False,
        "product_write_path must remain false",
    )
    _require(
        bundle["model_import_path"] is False,
        "model_import_path must remain false",
    )
    bundle["custody"] = _custody(bundle["custody"])
    bundle["identity"] = _identity(bundle["identity"])
    bundle["resources"] = _resources(bundle["resources"])
    bundle["abort"] = _abort(bundle["abort"])
    bundle["observations"] = _observations(
        bundle["observations"], case_limit=bundle["resources"]["case_limit"]
    )
    bundle["labels"] = _labels(
        bundle["labels"],
        [row["case_id"] for row in bundle["observations"]],
    )
    return bundle


def _closed(value: object, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ActivationMemoryContractError(f"{label} must be an object")
    missing = keys - set(value)
    extra = set(value) - keys
    if extra:
        raise ActivationMemoryContractError(
            f"{label} has extra fields: {sorted(extra)}"
        )
    if missing:
        raise ActivationMemoryContractError(
            f"{label} is missing fields: {sorted(missing)}"
        )
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ActivationMemoryContractError(message)


def _nonempty_string(value: object, label: str) -> str:
    _require(
        isinstance(value, str) and value.strip() == value and value,
        f"{label} must be a non-empty string",
    )
    return value


def _bool(value: object, label: str) -> bool:
    _require(type(value) is bool, f"{label} must be a boolean")
    return value


def _finite_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if type(value) is bool:
        raise ActivationMemoryContractError(f"{label} must not be a boolean")
    if type(value) not in {int, float}:
        raise ActivationMemoryContractError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ActivationMemoryContractError(f"{label} must be finite")
    _require(number >= minimum, f"{label} must be at least {minimum}")
    return value if type(value) is int else number


def _pinned_digest(value: object, label: str) -> str:
    digest = _nonempty_string(value, label)
    if len(digest) != 64 or any(char not in HEX64 for char in digest) or digest == "0" * 64:
        raise ActivationMemoryContractError(f"{label} must be a pinned 64-char digest")
    return digest


def _custody(value: object) -> dict[str, Any]:
    row = dict(_closed(value, _CUSTODY_KEYS, "custody"))
    row["class"] = _nonempty_string(row["class"], "custody.class")
    row["consent"] = _nonempty_string(row["consent"], "custody.consent")
    row["redacted"] = _bool(row["redacted"], "custody.redacted")
    _require(row["redacted"] is True, "custody.redacted must remain true")
    for field in (
        "authored_from_scratch",
        "protected_cases_included",
        "raw_activations_retained",
        "raw_prompts_retained",
        "upstream_bytes_included",
    ):
        row[field] = _bool(row[field], f"custody.{field}")
    _require(row["authored_from_scratch"] is True, "custody must be authored from scratch")
    _require(row["protected_cases_included"] is False, "protected cases are forbidden")
    _require(row["raw_activations_retained"] is False, "raw activations are forbidden")
    _require(row["raw_prompts_retained"] is False, "raw prompts are forbidden")
    _require(row["upstream_bytes_included"] is False, "upstream bytes are forbidden")
    return row


def _identity(value: object) -> dict[str, Any]:
    row = dict(_closed(value, _IDENTITY_KEYS, "identity"))
    for field in (
        "candidate_sha",
        "collector_license",
        "hardware_profile",
        "hook_layer",
        "model_license",
        "model_revision",
    ):
        row[field] = _nonempty_string(row[field], f"identity.{field}")
    row["sut_boundary"] = _nonempty_string(row["sut_boundary"], "identity.sut_boundary")
    _require(
        row["sut_boundary"] == SUT_BOUNDARY,
        "identity.sut_boundary must remain external-collector-json",
    )
    if type(row["seed"]) is bool:
        raise ActivationMemoryContractError("identity.seed must not be a boolean")
    _require(type(row["seed"]) is int, "identity.seed must be an int")
    for field in _DIGEST_FIELDS:
        row[field] = _pinned_digest(row[field], f"identity.{field}")
    return row


def _resources(value: object) -> dict[str, Any]:
    row = dict(_closed(value, frozenset(_RESOURCE_KEYS), "resources"))
    for field in _RESOURCE_KEYS:
        row[field] = _finite_number(row[field], f"resources.{field}")
    _require(type(row["case_limit"]) is int, "resources.case_limit must be an int")
    return row


def _abort(value: object) -> dict[str, Any]:
    row = dict(_closed(value, _ABORT_KEYS, "abort"))
    status = _nonempty_string(row["status"], "abort.status")
    _require(status in ABORT_STATUSES, "abort.status is unknown")
    row["status"] = status
    if status == "completed":
        _require(row["reason"] is None, "completed abort reason must be null")
        return row
    row["reason"] = _nonempty_string(row["reason"], "abort.reason")
    return row


def _observations(value: object, *, case_limit: int) -> list[dict[str, Any]]:
    _require(isinstance(value, list) and value, "observations must be a non-empty list")
    rows: list[dict[str, Any]] = []
    case_ids: list[str] = []
    for index, raw in enumerate(value):
        row = dict(_closed(raw, _OBSERVATION_KEYS, f"observations[{index}]"))
        row["case_id"] = _nonempty_string(row["case_id"], f"observations[{index}].case_id")
        row["family"] = _nonempty_string(row["family"], f"observations[{index}].family")
        _require(
            row["family"] in OBSERVATION_FAMILIES,
            f"observations[{index}].family is unknown",
        )
        row["value"] = _finite_number(row["value"], f"observations[{index}].value")
        row["redacted"] = _bool(row["redacted"], f"observations[{index}].redacted")
        _require(row["redacted"] is True, f"observations[{index}] must stay redacted")
        row["content_digest"] = _pinned_digest(
            row["content_digest"], f"observations[{index}].content_digest"
        )
        case_ids.append(row["case_id"])
        rows.append(row)
    _require(len(case_ids) == len(set(case_ids)), "observation case_id values must be unique")
    _require(len(rows) <= case_limit, "observations exceed the finite case_limit")
    return rows


def _labels(value: object, case_ids: list[str]) -> dict[str, dict[str, Any]]:
    _require(isinstance(value, Mapping), "labels must be an object")
    extra = set(value) - set(case_ids)
    missing = set(case_ids) - set(value)
    _require(
        not extra and not missing,
        "labels must bind one-to-one with observation case_id values",
    )
    labels: dict[str, dict[str, Any]] = {}
    for case_id in case_ids:
        row = dict(_closed(value[case_id], _LABEL_KEYS, f"labels.{case_id}"))
        row["case_id"] = _nonempty_string(row["case_id"], f"labels.{case_id}.case_id")
        _require(row["case_id"] == case_id, f"labels.{case_id}.case_id must match its key")
        row["owner"] = _nonempty_string(row["owner"], f"labels.{case_id}.owner")
        _require(row["owner"] == "scorer", f"labels.{case_id}.owner must be scorer-owned")
        row["family"] = _nonempty_string(row["family"], f"labels.{case_id}.family")
        _require(
            row["family"] in OBSERVATION_FAMILIES,
            f"labels.{case_id}.family is unknown",
        )
        row["expected_tripwire"] = _bool(
            row["expected_tripwire"], f"labels.{case_id}.expected_tripwire"
        )
        labels[case_id] = row
    return labels
