"""Source-only BEAM reader disclosure envelope."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from collections.abc import Mapping

from eval.public.bundle import _canonical
from eval.public.runner import validate_candidate_manifest

_SCHEMA_VERSION = "beam-reader-disclosure-v1"
_CONFIG_SCHEMA_VERSION = "beam-reader-judge-config-v1"
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_READER_KEYS = {
    "config",
    "config_sha256",
    "model_content_sha256",
    "model_revision",
    "name",
    "provider",
    "selector",
}
_JUDGE_KEYS = _READER_KEYS | {"prompt", "prompt_sha256"}


class BeamDisclosureError(ValueError):
    """The BEAM disclosure is not canonical."""


def build_reader_judge_config(
    reader: object,
    judge: object,
) -> dict[str, object]:
    """Build the canonical source-only BEAM reader and judge configuration."""
    try:
        canonical_reader = _canonical_metadata(reader, _READER_KEYS)
        canonical_judge = _canonical_metadata(judge, _JUDGE_KEYS)
        _validate_metadata(canonical_reader)
        _validate_metadata(canonical_judge, content_key="prompt")
    except Exception as exc:
        raise BeamDisclosureError("reader or judge metadata is invalid") from exc

    return {
        "schema_version": _CONFIG_SCHEMA_VERSION,
        "reader": canonical_reader,
        "judge": canonical_judge,
    }


def _canonical_metadata(value: object, expected_keys: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ValueError("metadata fields are not canonical")
    return json.loads(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    )


def _validate_metadata(
    value: dict[str, object],
    *,
    content_key: str = "config",
) -> None:
    for key in ("name", "provider", "selector", "model_revision"):
        item = value[key]
        if not isinstance(item, str) or not item or item != item.strip():
            raise ValueError(f"{key} must be a canonical string")

    for key in ("model_content_sha256", "config_sha256", f"{content_key}_sha256"):
        item = value[key]
        if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
            raise ValueError(f"{key} must be exact lowercase SHA-256")

    selector = value["selector"]
    revision = value["model_revision"]
    digest = value["model_content_sha256"]
    if revision != selector and not selector.endswith(f"@{revision}"):
        raise ValueError("model revision does not pin the selector")
    if revision.startswith("sha256:") and revision != f"sha256:{digest}":
        raise ValueError("model revision does not match model content")

    content = value[content_key]
    if not isinstance(content, dict) or not content:
        raise ValueError(f"{content_key} must be a non-empty object")
    if hashlib.sha256(_canonical(content)).hexdigest() != value[f"{content_key}_sha256"]:
        raise ValueError(f"{content_key} digest mismatch")

    if content_key != "config":
        if not isinstance(value["config"], dict) or not value["config"]:
            raise ValueError("config must be a non-empty object")
        if hashlib.sha256(_canonical(value["config"])).hexdigest() != value["config_sha256"]:
            raise ValueError("config digest mismatch")


def build_disclosure(
    candidate_manifest: object,
    *,
    dataset_revision: object,
    protocol_id: object,
) -> dict[str, object]:
    """Build the canonical source-only BEAM reader disclosure."""
    if not isinstance(dataset_revision, str) or _REVISION.fullmatch(dataset_revision) is None:
        raise BeamDisclosureError("dataset revision must be exact lowercase 40-hex")
    if (
        not isinstance(protocol_id, str)
        or not protocol_id
        or protocol_id != protocol_id.strip()
    ):
        raise BeamDisclosureError("protocol identifier must be non-empty and canonical")
    if not isinstance(candidate_manifest, Mapping):
        raise BeamDisclosureError("candidate manifest must be a mapping")

    try:
        manifest = deepcopy(dict(candidate_manifest))
        validate_candidate_manifest(manifest)
        manifest = json.loads(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except Exception as exc:
        raise BeamDisclosureError("candidate manifest is invalid") from exc

    return {
        "schema_version": _SCHEMA_VERSION,
        "dataset_revision": dataset_revision,
        "protocol_id": protocol_id,
        "candidate_manifest": manifest,
    }
