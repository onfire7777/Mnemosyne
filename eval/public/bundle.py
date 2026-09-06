"""Canonical public benchmark bundle custody, verification, and reproduction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from eval.harness.metrics import wilson_interval

REQUIRED = (
    "README.md",
    "benchmark.json",
    "build.json",
    "config.json",
    "judge.json",
    "metrics.json",
    "reproduce.sh",
    "traces.jsonl",
)
SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"-----(?:BEGIN|END) [A-Z ]*PRIVATE KEY-----)"
)
CANONICAL_REPLAY_VOLATILE_FIELDS = frozenset(
    {
        "host_path",
        "path",
        "receipt_id",
        "rss_samples_bytes",
        "runtime_timestamp_utc",
        "signature",
        "wall_time_ms",
    }
)
_CANONICAL_REPLAY_SEEDS = {
    "wmbs-m01-development": (20260728,),
    "wmbs-m02-retrieval-development": (20260801,),
    "wmbs-m03-valid-time-development": (11, 23, 37, 53, 71),
    "wmbs-m05-provenance-development": (13, 29, 41, 59, 73),
    "wmbs-m10-development": (0, 1, 2, 3, 4),
}
_CANONICAL_REPLAY_MANIFESTS = {
    "bundle_manifest_sha256",
    "fixture_manifest_sha256",
    "generator_manifest_sha256",
}
_CANONICAL_REPLAY_REQUIRED = {
    "abi_schema",
    "build",
    "config",
    "fixture",
    "judge",
    "manifests",
    "metrics",
    "seed_records",
    "suite",
    "sut_outputs",
    "traces",
    "volatile",
}
REPRODUCIBILITY_BUNDLE_SCHEMA_VERSION = "mnemosyne.reproducibility-bundle/v1"
REPRODUCIBILITY_BUNDLE_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "schema" / "reproducibility-bundle-v1.schema.json"
)
REPRODUCIBILITY_MANIFEST_NAME = "reproducibility-bundle.json"
REPRODUCTION_ARGV = [
    "uv",
    "run",
    "--locked",
    "mneme",
    "eval-public",
    "--reproduce-bundle",
    "BUNDLE",
    "--out-dir",
    "DEST",
]
_REPRO_REQUIRED_FIELDS = (
    "schema_version",
    "result_ref",
    "ledger_ref",
    "manifests",
    "traces",
    "config",
    "build",
    "environment",
    "metrics",
    "intervals",
    "hashes",
    "rights",
    "custody",
    "operator",
    "command",
    "track_kind",
    "lineage",
    "canonical_replay",
    "publication",
)
_REPRO_TRACK_KINDS = ("OFFICIAL-UPSTREAM", "ENHANCED-SUCCESSOR", "DEVELOPMENT")
_REPRO_MANIFEST_REF_KEYS = (
    "benchmark",
    "dataset_split",
    "fixture",
    "generator",
    "adapter",
    "scorer",
    "baseline",
    "judge",
    "reader",
    "model",
    "prompt",
    "fidelity",
    "parent",
    "difference",
)
_REPRO_PUBLICATION_FLAGS = (
    "certified",
    "headline",
    "independent",
    "independent_external_reproduction",
    "pbpp_headline_eligible",
    "publishable",
)
_REPRO_CUSTODY_CLASSES = (
    "development-public",
    "operator-held-out",
    "certification-held-out",
)
_REPRO_OPERATOR_ROLES = ("operator", "independent", "custodian")
_NAMED_DIGEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*@sha256:[0-9a-f]{64}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_REPRO_JSON_DEPTH = 64
_MAX_REPRO_FILE_BYTES = 16 * 1024 * 1024
_REGISTERED_SCORING_PROFILES = {
    "smoke-hit-at-k-v1": ("deterministic-retrieval", "wilson"),
    "longmemeval-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
    "hipporag-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
    "qa-em-f1-v1": ("qa", "bootstrap"),
    "pm-bench-action-v1": ("deterministic-action", "wilson"),
    "triggerbench-action-v1": ("deterministic-action", "wilson"),
    "working-memory-action-v1": ("deterministic-action", "bootstrap"),
    "wmbs-m01-v1": ("whole-memory-development", "descriptive"),
    "wmbs-m03-valid-time-v1": ("whole-memory-development", "descriptive"),
    "wmbs-m05-v1": ("whole-memory-development", "descriptive"),
    "wmbs-m10-v1": ("whole-memory-development", "descriptive"),
}
_REPRO_CANONICAL_HIT_AT_K_PROFILE = "smoke-hit-at-k-v1"


class BundleError(ValueError):
    """Bundle failed closed under the public custody contract."""


def canonical_replay_fixture_custody(payload: object) -> bool:
    """Validate that the closed fixture reference is bound to its manifest."""
    if not isinstance(payload, dict):
        raise BundleError("canonical replay payload must be an object")
    suite = payload.get("suite")
    fixture = payload.get("fixture")
    manifests = payload.get("manifests")
    if not isinstance(fixture, str):
        raise BundleError("fixture reference custody is incomplete")
    fixture_suite, separator, fixture_digest = fixture.rpartition("@sha256:")
    if (
        separator != "@sha256:"
        or fixture_suite != suite
        or re.fullmatch(r"[0-9a-f]{64}", fixture_digest) is None
        or not isinstance(manifests, dict)
        or fixture_digest != manifests.get("fixture_manifest_sha256")
    ):
        raise BundleError("fixture manifest custody does not match fixture reference")
    return True


def canonical_replay_projection(payload: object) -> object:
    """Return the deterministic M15 equality projection after custody checks."""
    if not isinstance(payload, dict):
        raise BundleError("canonical replay payload must be an object")
    missing = _CANONICAL_REPLAY_REQUIRED - payload.keys()
    if missing:
        fields = ", ".join(field.replace("_", " ") for field in sorted(missing))
        raise BundleError(f"canonical replay payload is missing: {fields}")
    suite = payload.get("suite")
    expected_seeds = _CANONICAL_REPLAY_SEEDS.get(suite)
    if expected_seeds is None:
        raise BundleError("unsupported stochastic equality suite")
    seeds = payload.get("seed_records")
    if (
        not isinstance(seeds, list)
        or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
        or len(seeds) != len(expected_seeds)
        or set(seeds) != set(expected_seeds)
    ):
        raise BundleError("seed records custody is incomplete or unsupported")
    manifests = payload.get("manifests")
    if (
        not isinstance(manifests, dict)
        or set(manifests) != _CANONICAL_REPLAY_MANIFESTS
        or any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in manifests.values()
        )
    ):
        raise BundleError("manifests custody is incomplete")
    canonical_replay_fixture_custody(payload)
    config = payload.get("config")
    if not isinstance(config, dict) or config.get("locale") != "C":
        raise BundleError("locale must be frozen to C")
    if config.get("timezone") != "UTC":
        raise BundleError("timezone must be frozen to UTC")

    def project(value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise BundleError("non-finite numbers are forbidden")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise BundleError("canonical replay map keys must be strings")
            return {
                key: project(item)
                for key, item in value.items()
                if key not in CANONICAL_REPLAY_VOLATILE_FIELDS
            }
        if isinstance(value, list):
            return [project(item) for item in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        raise BundleError(f"canonical replay contains ambiguous value: {type(value).__name__}")

    try:
        projection = project(payload)
        _canonical(projection)
    except BundleError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise BundleError("canonical replay projection is not canonical JSON") from exc
    return projection


def canonical_replay_digest(payload: object) -> str:
    """Digest the validated M15 projection with the existing canonical JSON path."""
    return hashlib.sha256(_canonical(canonical_replay_projection(payload))).hexdigest()


def _sha256_ref(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _assert_reproduction_checkout(expected_sha: str) -> None:
    """Require the invoking checkout (cwd) to match the bound commit and be clean."""
    if not isinstance(expected_sha, str) or _HEX_COMMIT.fullmatch(expected_sha) is None:
        raise BundleError("bound commit is unavailable")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError("reproduction checkout is unavailable")
    actual = result.stdout.strip()
    if actual != expected_sha:
        raise BundleError("reproduction checkout does not match bound commit")
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    if dirty.returncode != 0 or dirty.stdout:
        raise BundleError("reproduction checkout is dirty")


def _json_depth(value: object, depth: int = 0) -> int:
    if depth > _MAX_REPRO_JSON_DEPTH:
        raise BundleError("JSON nesting exceeds the closed bound")
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


def _closed_object(value: object, allowed: tuple[str, ...] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleError(f"{label} must be an object")
    extra = set(value) - set(allowed)
    if extra:
        raise BundleError(f"unknown field in {label}")
    missing = [field for field in allowed if field not in value]
    if missing:
        raise BundleError(f"missing {missing[0]}")
    return value


def _require_named_digest(value: object, label: str, *, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        raise BundleError(f"missing {label}")
    if not isinstance(value, str) or _NAMED_DIGEST.fullmatch(value) is None:
        raise BundleError(f"{label} must be a canonical sha256 reference")
    return value


def _require_sha256_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None:
        raise BundleError(f"{label} must be lowercase sha256: hex")
    return value


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleError(f"missing {label}")
    return value


def _require_enum(value: object, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise BundleError(f"unknown {label}")
    return str(value)


def _validate_repro_schema(manifest: object) -> None:
    try:
        schema = json.loads(REPRODUCIBILITY_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError("reproducibility schema is invalid") from exc
    try:
        Draft202012Validator(schema).validate(manifest)
    except ValidationError as exc:
        path = "/".join(str(part) for part in exc.absolute_path)
        detail = f"{path}: {exc.message}" if path else exc.message
        raise BundleError(f"reproducibility manifest fails schema: {detail}") from exc


def _named_digest_hex(value: object, label: str) -> str:
    ref = _require_named_digest(value, label)
    if ref is None:
        raise BundleError(f"missing {label}")
    return ref.rsplit("@sha256:", 1)[1]


def _require_bound_digest(value: object, label: str, payloads: dict[str, bytes]) -> str:
    digest = _named_digest_hex(value, label)
    if not any(hashlib.sha256(payload).hexdigest() == digest for payload in payloads.values()):
        raise BundleError(f"{label} digest is not bound to an inventory file")
    return digest


def _validate_reproducibility_manifest(manifest: object) -> dict[str, Any]:
    _validate_repro_schema(manifest)
    payload = _closed_object(manifest, _REPRO_REQUIRED_FIELDS, "reproducibility manifest")
    _json_depth(payload)
    if payload.get("schema_version") != REPRODUCIBILITY_BUNDLE_SCHEMA_VERSION:
        raise BundleError("unknown reproducibility manifest version")
    if payload.get("command") != REPRODUCTION_ARGV:
        raise BundleError("command must be the exact closed argv")
    track_kind = payload.get("track_kind")
    if track_kind not in _REPRO_TRACK_KINDS:
        raise BundleError("unknown track_kind")
    _require_named_digest(payload.get("result_ref"), "result_ref")
    if payload.get("ledger_ref") is not None:
        _require_named_digest(payload.get("ledger_ref"), "ledger_ref")
    refs = _closed_object(payload.get("manifests"), _REPRO_MANIFEST_REF_KEYS, "manifests")
    required_refs = {
        "benchmark",
        "dataset_split",
        "fixture",
        "generator",
        "adapter",
        "scorer",
        "baseline",
    }
    optional_refs = {"judge", "reader", "model", "prompt", "fidelity", "parent", "difference"}
    for key in required_refs:
        _require_named_digest(refs.get(key), key)
    for key in optional_refs:
        _require_named_digest(refs.get(key), key, optional=True)
    if track_kind == "OFFICIAL-UPSTREAM":
        _require_named_digest(refs.get("fidelity"), "fidelity")
        if refs.get("parent") is not None or refs.get("difference") is not None:
            raise BundleError("official records cannot carry successor manifests")
    elif track_kind == "ENHANCED-SUCCESSOR":
        _require_named_digest(refs.get("parent"), "parent")
        _require_named_digest(refs.get("difference"), "difference")
        if refs.get("fidelity") is not None:
            raise BundleError("successor records cannot carry an official fidelity manifest")
    else:
        if any(refs.get(key) is not None for key in ("fidelity", "parent", "difference")):
            raise BundleError("development records cannot carry official or successor manifests")
    traces = _closed_object(
        payload.get("traces"),
        ("path", "trace_index_digest", "seed_records", "retries", "aborts"),
        "traces",
    )
    if traces.get("path") != "traces.jsonl":
        raise BundleError("traces path must be traces.jsonl")
    _require_sha256_digest(traces.get("trace_index_digest"), "trace_index_digest")
    config = _closed_object(
        payload.get("config"),
        ("path", "config_digest", "locale", "timezone"),
        "config",
    )
    if config.get("path") != "config.json":
        raise BundleError("config path must be config.json")
    _require_sha256_digest(config.get("config_digest"), "config_digest")
    if config.get("locale") != "C" or config.get("timezone") != "UTC":
        raise BundleError("locale and timezone must be frozen to C/UTC")
    build = _closed_object(
        payload.get("build"),
        (
            "path",
            "build_fingerprint",
            "candidate_git_sha",
            "dirty",
            "lockfile",
            "toolchain",
            "environment_contract",
        ),
        "build",
    )
    if build.get("path") != "build.json":
        raise BundleError("build path must be build.json")
    _require_sha256_digest(build.get("build_fingerprint"), "build_fingerprint")
    if not isinstance(build.get("candidate_git_sha"), str) or _HEX_COMMIT.fullmatch(
        str(build["candidate_git_sha"])
    ) is None:
        raise BundleError("bound commit is unavailable")
    if build.get("dirty") is not False:
        raise BundleError("dirty checkout is forbidden")
    _require_named_digest(build.get("lockfile"), "lockfile")
    if build.get("environment_contract") != "uv run --locked":
        raise BundleError("environment contract must be uv run --locked")
    environment = _closed_object(
        payload.get("environment"),
        (
            "path",
            "allowlist",
            "locale",
            "timezone",
            "platform",
            "runtime",
            "wheelhouse_digest",
        ),
        "environment",
    )
    if environment.get("path") != "environment.json":
        raise BundleError("environment path must be environment.json")
    if environment.get("locale") != "C" or environment.get("timezone") != "UTC":
        raise BundleError("locale and timezone must be frozen to C/UTC")
    publication = _closed_object(
        payload.get("publication"), _REPRO_PUBLICATION_FLAGS, "publication"
    )
    if any(publication.get(flag) is not False for flag in _REPRO_PUBLICATION_FLAGS):
        raise BundleError("reproduction is not headline, independent, or certified")
    rights = payload.get("rights")
    if not isinstance(rights, dict):
        raise BundleError("missing rights")
    _closed_object(
        rights,
        (
            "software_license",
            "data_license",
            "source_revision",
            "redistribution",
            "pii",
            "consent",
            "takedown",
            "disclosure_state",
        ),
        "rights",
    )
    custody = _closed_object(payload.get("custody"), ("class", "declaration"), "custody")
    _require_enum(custody.get("class"), _REPRO_CUSTODY_CLASSES, "custody")
    _require_nonempty_string(custody.get("declaration"), "custody")
    operator = _closed_object(
        payload.get("operator"),
        ("identity", "role", "signer_role", "disclosure_state"),
        "operator",
    )
    _require_nonempty_string(operator.get("identity"), "operator")
    _require_enum(operator.get("role"), _REPRO_OPERATOR_ROLES, "operator")
    _require_enum(operator.get("signer_role"), _REPRO_OPERATOR_ROLES, "operator")
    if operator.get("disclosure_state") != "disclosed":
        raise BundleError("missing operator")
    lineage = payload.get("lineage")
    if track_kind == "DEVELOPMENT":
        if lineage != {}:
            raise BundleError("development lineage must be empty")
    elif track_kind == "OFFICIAL-UPSTREAM":
        if not isinstance(lineage, dict) or "fidelity" not in lineage:
            raise BundleError("official records require a fidelity manifest")
        _closed_object(lineage, ("fidelity",), "lineage")
    else:
        if not isinstance(lineage, dict) or any(
            key not in lineage
            for key in (
                "parent_official_record_id",
                "parent_construct_digest",
                "difference_manifest_digest",
            )
        ):
            raise BundleError("successor records require parent and difference manifests")
        _closed_object(
            lineage,
            (
                "parent_official_record_id",
                "parent_construct_digest",
                "difference_manifest_digest",
            ),
            "lineage",
        )
    hashes = payload.get("hashes")
    if not isinstance(hashes, list) or not hashes:
        raise BundleError("missing hashes")
    seen_paths: set[str] = set()
    for entry in hashes:
        item = _closed_object(
            entry, ("path", "size", "media_type", "canonicalization", "sha256"), "hashes"
        )
        path = item.get("path")
        if not isinstance(path, str) or _RELATIVE_PATH.fullmatch(path) is None:
            raise BundleError("path must be a relative normalized file path")
        if path in seen_paths:
            raise BundleError("duplicate normalized path")
        seen_paths.add(path)
        _require_sha256_digest(item.get("sha256"), "inventory digest")
    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise BundleError("missing metrics")
    for metric in metrics:
        if not isinstance(metric, dict):
            raise BundleError("missing metrics")
        extra = set(metric) - {
            "family",
            "name",
            "version",
            "value",
            "unit",
            "numerator",
            "denominator",
            "sample_count",
            "uncertainty_method",
            "uncertainty_parameters",
            "confidence_level",
            "interval",
            "exclusions",
            "missing_count",
            "unsupported_count",
            "failed_count",
            "aborted_count",
            "not_measured_count",
        }
        if extra:
            raise BundleError("unknown field in metrics")
        missing = [
            field
            for field in (
                "family",
                "name",
                "version",
                "value",
                "unit",
                "numerator",
                "denominator",
                "sample_count",
                "uncertainty_method",
                "uncertainty_parameters",
                "confidence_level",
                "interval",
                "exclusions",
                "missing_count",
                "unsupported_count",
                "failed_count",
                "aborted_count",
                "not_measured_count",
            )
            if field not in metric
        ]
        if missing:
            raise BundleError(f"missing {missing[0]}")
    return payload


def _inventory_bytes(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    hashes = manifest["hashes"]
    listed = [entry["path"] for entry in hashes]
    if len(listed) != len(set(listed)):
        raise BundleError("duplicate normalized path")
    listed_set = set(listed)
    payloads: dict[str, bytes] = {}
    scanned: dict[str, bytes] = {}
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise BundleError(f"links and non-files are forbidden: {entry.name}")
        if entry.resolve().parent != root.resolve():
            raise BundleError(f"path escapes bundle: {entry.name}")
        if entry.stat().st_size > _MAX_REPRO_FILE_BYTES:
            raise BundleError("bundle file exceeds the closed size bound")
        scanned[entry.name] = entry.read_bytes()
    raw = b"".join(scanned[name] for name in sorted(scanned))
    if SECRET.search(raw.decode("utf-8", errors="replace")):
        raise BundleError("secret-like material detected")
    expected = listed_set | {REPRODUCIBILITY_MANIFEST_NAME}
    extras = set(scanned) - expected
    if extras or any(name not in scanned for name in expected):
        raise BundleError("inventory mismatch")
    payloads = {name: scanned[name] for name in expected}
    for name, payload in payloads.items():
        text = payload.decode("utf-8", errors="replace")
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                _parse_json(line, name)
        elif name.endswith(".json"):
            _parse_json(text, name)
    for entry in hashes:
        path = str(entry["path"])
        payload = payloads[path]
        if len(payload) != entry["size"] or _sha256_ref(payload) != entry["sha256"]:
            raise BundleError(f"digest mismatch: {path}")
    return payloads


def _bound_repro_k(config: object) -> int:
    if not isinstance(config, dict):
        raise BundleError("bound k is unavailable")
    k = config.get("k")
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise BundleError("bound k is unavailable")
    return k


def _bound_repro_scoring_profile(config: object) -> str:
    if not isinstance(config, dict):
        raise BundleError("unknown scoring profile")
    profile = config.get("scoring_profile")
    if not isinstance(profile, str) or profile not in _REGISTERED_SCORING_PROFILES:
        raise BundleError("unknown scoring profile")
    family, method = _REGISTERED_SCORING_PROFILES[profile]
    if config.get("family") != family or config.get("interval_method") != method:
        raise BundleError("wrong interval-family metadata")
    if profile != _REPRO_CANONICAL_HIT_AT_K_PROFILE:
        raise BundleError("scoring profile cannot be recomputed")
    return profile


def _score_repro_traces(traces: list[dict[str, Any]], k: int) -> tuple[int, int]:
    if k < 1:
        raise BundleError("bound k is unavailable")
    successes = 0
    total = 0
    for trace in traces:
        if not isinstance(trace, dict):
            raise BundleError("metrics do not recompute from traces")
        hits = trace.get("ranked_retrieved_hits")
        gold = trace.get("gold_references")
        if not isinstance(hits, list) or not isinstance(gold, list):
            raise BundleError("metrics do not recompute from traces")
        try:
            unique_hits = set(hits)
        except TypeError as exc:
            raise BundleError("ranked retrieved hits are malformed") from exc
        if len(hits) != len(unique_hits):
            raise BundleError("duplicate ranked retrieved ids")
        successes += bool(set(hits[:k]) & set(gold))
        total += 1
    if total == 0:
        raise BundleError("metrics do not recompute from traces")
    return successes, total


def _measured_from_repro_score(successes: int, total: int) -> dict[str, Any]:
    expected = wilson_interval(successes, total).as_dict()
    return {
        "family": "deterministic-retrieval",
        "interval": {
            "confidence": 0.95,
            "high": expected["ci_high"],
            "low": expected["ci_low"],
            "method": expected["ci_method"],
        },
        "metric": "hit_at_k",
        "successes": successes,
        "total": total,
        "trace_count": total,
        "value": expected["point"],
    }


def _recompute_repro_metrics(
    traces: list[dict[str, Any]],
    measured: object,
    manifest_metrics: object,
    manifest_intervals: object,
    *,
    config: object,
) -> dict[str, Any]:
    if not isinstance(measured, dict):
        raise BundleError("missing metrics")
    k = _bound_repro_k(config)
    version = _bound_repro_scoring_profile(config)
    successes, total = _score_repro_traces(traces, k)
    recomputed = _measured_from_repro_score(successes, total)
    expected_value = recomputed["value"]
    expected_interval = recomputed["interval"]
    if any(measured.get(key) != recomputed[key] for key in recomputed if key != "interval"):
        raise BundleError("metrics do not recompute from traces")
    if not isinstance(manifest_metrics, list) or not manifest_metrics:
        raise BundleError("missing metrics")
    measured_interval = measured.get("interval", {})
    if not isinstance(measured_interval, dict) or any(
        measured_interval.get(key) != expected_interval[key] for key in expected_interval
    ):
        raise BundleError("intervals do not recompute from traces")
    for declared in manifest_metrics:
        if not isinstance(declared, dict):
            raise BundleError("missing metrics")
        declared_interval = declared.get("interval", {})
        if (
            declared.get("family") != "retrieval"
            or declared.get("name") != "hit_at_k"
            or declared.get("version") != version
            or declared.get("unit") != "ratio"
            or declared.get("uncertainty_method") != "wilson"
            or declared.get("uncertainty_parameters") != {"z": 1.96}
            or declared.get("confidence_level") != 0.95
            or declared.get("exclusions") != []
            or declared.get("missing_count") != 0
            or declared.get("unsupported_count") != 0
            or declared.get("failed_count") != 0
            or declared.get("aborted_count") != 0
            or declared.get("not_measured_count") != 0
            or declared.get("numerator") != successes
            or declared.get("denominator") != total
            or declared.get("sample_count") != total
            or declared.get("value") != expected_value
            or not isinstance(declared_interval, dict)
            or declared_interval.get("low") != expected_interval["low"]
            or declared_interval.get("high") != expected_interval["high"]
        ):
            raise BundleError("metrics do not recompute from traces")
    if not isinstance(manifest_intervals, list) or not manifest_intervals:
        raise BundleError("missing intervals")
    for interval in manifest_intervals:
        if (
            not isinstance(interval, dict)
            or interval.get("metric") != "hit_at_k"
            or interval.get("low") != expected_interval["low"]
            or interval.get("high") != expected_interval["high"]
            or interval.get("method") != expected_interval["method"]
            or interval.get("confidence_level") != 0.95
        ):
            raise BundleError("intervals do not recompute from traces")
    if len(manifest_metrics) != 1 or len(manifest_intervals) != 1:
        raise BundleError("metrics do not recompute from traces")
    return recomputed


def _verify_reproducibility_bundle(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise BundleError("bundle must be a real directory, not a link")
    manifest_path = root / REPRODUCIBILITY_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BundleError("reproducibility manifest must be a real file, not a link")
    if not REPRODUCIBILITY_BUNDLE_SCHEMA_PATH.is_file():
        raise BundleError("reproducibility schema is missing")
    try:
        loaded_manifest = _load_json(manifest_path)
    except BundleError as exc:
        cause = exc.__cause__
        if isinstance(cause, ValueError) and "duplicate" in str(cause):
            raise BundleError("duplicate JSON key in reproducibility manifest") from exc
        raise
    manifest = _validate_reproducibility_manifest(loaded_manifest)
    payloads = _inventory_bytes(root, manifest)
    for required in ("traces.jsonl", "config.json", "build.json", "result.json", "bundle-manifest.json"):
        if required not in payloads:
            raise BundleError(f"missing {required}")
    if manifest["build"]["build_fingerprint"] != _sha256_ref(payloads["build.json"]):
        raise BundleError("build_fingerprint digest mismatch")
    if manifest["config"]["config_digest"] != _sha256_ref(payloads["config.json"]):
        raise BundleError("config_digest digest mismatch")
    if manifest["traces"]["trace_index_digest"] != _sha256_ref(payloads["traces.jsonl"]):
        raise BundleError("trace_index_digest digest mismatch")
    result = _load_json(root / "result.json")
    if manifest["result_ref"] != f"result-v2@sha256:{hashlib.sha256(payloads['result.json']).hexdigest()}":
        raise BundleError("result digest mismatch")
    if "uv.lock" not in payloads:
        raise BundleError("missing lockfile")
    if manifest["build"]["lockfile"] != f"uv.lock@sha256:{hashlib.sha256(payloads['uv.lock']).hexdigest()}":
        raise BundleError("lockfile digest mismatch")
    refs = manifest["manifests"]
    for key, ref in refs.items():
        if ref is not None:
            _require_bound_digest(ref, key, payloads)
    from leaderboard.validate import validate_record, verify_result_digests

    errors = validate_record(result)
    if errors:
        raise BundleError("result-v2 is invalid: " + ", ".join(errors))
    digest_errors = verify_result_digests(
        result,
        {
            "build.json": payloads["build.json"],
            "config.json": payloads["config.json"],
            "bundle-manifest.json": payloads["bundle-manifest.json"],
            "traces.jsonl": payloads["traces.jsonl"],
        },
    )
    if digest_errors:
        raise BundleError("result digest mismatch")
    if result.get("track_kind") != manifest["track_kind"]:
        raise BundleError("track_kind mismatch")
    if result.get("run_commit") != manifest["build"]["candidate_git_sha"]:
        raise BundleError("result run_commit does not match bound commit")
    if "canonical-replay.json" not in payloads:
        raise BundleError("canonical replay artifact is missing")
    replay = _load_json(root / "canonical-replay.json")
    expected = manifest["canonical_replay"]
    if (
        not isinstance(expected, dict)
        or expected.get("digest") != canonical_replay_digest(replay)
        or expected.get("suite") != replay.get("suite")
        or expected.get("seed_records") != replay.get("seed_records")
    ):
        raise BundleError("canonical replay digest mismatch")
    if manifest.get("ledger_ref") is not None:
        from leaderboard.ledger import LedgerError
        from leaderboard.ledger import _canonical as ledger_canonical
        from leaderboard.ledger import verify_ledger

        ledger_path = root / "ledger.jsonl"
        public_key = root / "ledger-public.pem"
        lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")
        if "ledger.jsonl" not in payloads or "ledger-public.pem" not in payloads:
            raise BundleError("missing ledger inclusion receipt")
        try:
            entries = verify_ledger(ledger_path, public_key)
        except LedgerError as exc:
            raise BundleError("ledger verification failed") from exc
        finally:
            if lock_path.is_file() and not lock_path.is_symlink():
                try:
                    lock_path.unlink()
                except OSError:
                    pass
        matched = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("result") == result
        ]
        if not matched:
            raise BundleError("ledger result reference mismatch")
        if not any(
            manifest["ledger_ref"]
            == f"ledger-entry@sha256:{hashlib.sha256(ledger_canonical(entry)).hexdigest()}"
            for entry in matched
        ):
            raise BundleError("ledger_ref digest mismatch")
    traces = [
        _parse_json(line, "traces.jsonl")
        for line in payloads["traces.jsonl"].decode("utf-8").splitlines()
        if line
    ]
    if "metrics.json" not in payloads:
        raise BundleError("missing metrics")
    _recompute_repro_metrics(
        traces,
        _load_json(root / "metrics.json"),
        manifest.get("metrics"),
        manifest.get("intervals"),
        config=_load_json(root / "config.json"),
    )
    publication = manifest["publication"]
    return {
        "family": "reproducibility",
        "headline_eligible": False,
        "publication": publication,
        "repro_002": "blocked",
        "run_commit": manifest["build"]["candidate_git_sha"],
        "schema_version": REPRODUCIBILITY_BUNDLE_SCHEMA_VERSION,
        "suite": (
            result.get("benchmark") if isinstance(result.get("benchmark"), str) else None
        ),
        "track_kind": manifest["track_kind"],
        "valid": True,
    }


def _reproduce_reproducibility_bundle(source: Path, destination: Path) -> dict[str, Any]:
    verified = _verify_reproducibility_bundle(source)
    _assert_reproduction_checkout(str(verified["run_commit"]))
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        source_manifest = _load_json(source / REPRODUCIBILITY_MANIFEST_NAME)
        owned = [
            str(entry["path"])
            for entry in source_manifest["hashes"]
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        ] + [REPRODUCIBILITY_MANIFEST_NAME]
        for name in owned:
            if name == "metrics.json":
                continue
            src = source / name
            if src.is_symlink() or not src.is_file():
                raise BundleError(f"links and non-files are forbidden: {name}")
            shutil.copyfile(src, temp / name, follow_symlinks=False)
        config = _load_json(temp / "config.json")
        traces = [
            _parse_json(line, "traces.jsonl")
            for line in (temp / "traces.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        successes, total = _score_repro_traces(traces, _bound_repro_k(config))
        recomputed = _measured_from_repro_score(successes, total)
        _recompute_repro_metrics(
            traces,
            recomputed,
            source_manifest.get("metrics"),
            source_manifest.get("intervals"),
            config=config,
        )
        _write_json(temp / "metrics.json", recomputed)
        _verify_reproducibility_bundle(temp)
        for name in owned:
            if (temp / name).read_bytes() != (source / name).read_bytes():
                raise BundleError(f"reproduction mismatch: {name}")
        temp.rename(destination)
        return verified
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def write_bundle(
    destination: Path,
    *,
    benchmark: dict[str, Any],
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    traces: list[dict[str, Any]],
    candidate_manifest_path: Path | str | None = None,
) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    try:
        _write_json(temp / "benchmark.json", {"data": benchmark, "metadata": metadata})
        build = {
            "environment_contract": "uv run --locked",
            "system_seam": metadata.get("system_seam", "public-cli-subprocess"),
            "version": 1,
        }
        if metadata["family"] == "qa":
            build["candidate_git_sha"] = _git_sha()
        _write_json(
            temp / "build.json",
            build,
        )
        _write_json(
            temp / "config.json",
            {
                "family": metadata["family"],
                "interval_method": metadata["interval_method"],
                **({"interval_methods": metadata.get("interval_methods")} if metadata["family"] == "qa" else {}),
                "scoring_profile": metadata.get("scoring_profile", "smoke-hit-at-k-v1"),
                "suite": metadata["suite"],
            },
        )
        if metadata["family"] == "qa":
            custody = metadata.get("reader_custody")
            if not isinstance(custody, dict):
                raise BundleError("QA bundle requires reader custody")
            _write_json(
                temp / "judge.json",
                {
                    "custody": custody,
                    "judge": "benchmark-owned-qa-em-f1-v1",
                    "reader": custody.get("reader", {}).get("name"),
                },
            )
            if candidate_manifest_path is None:
                raise BundleError("QA bundle requires an external candidate manifest path")
            source = Path(candidate_manifest_path)
            _reject_symlink_path(source)
            if not source.is_file():
                raise BundleError("candidate manifest path must be a real file")
            candidate_raw = source.read_bytes()
            candidate = _parse_json(candidate_raw.decode("utf-8"), "candidate manifest")
            from eval.public.runner import validate_candidate_manifest

            try:
                validate_candidate_manifest(candidate, expected_git_sha=build["candidate_git_sha"])
            except ValueError as exc:
                raise BundleError("candidate manifest does not bind bundle-producing git SHA") from exc
            if candidate_raw != _canonical(candidate):
                raise BundleError("candidate manifest bytes must be canonical")
            (temp / "candidate-manifest.json").write_bytes(candidate_raw)
        else:
            _write_json(
                temp / "judge.json",
                {"judge": None, "reader": None, "reason": f"{metadata['family']} family"},
            )
        _write_json(temp / "metrics.json", metrics)
        (temp / "traces.jsonl").write_bytes(
            b"".join(_canonical(trace) for trace in traces)
        )
        (temp / "README.md").write_text(
            "# PBPP development bundle\n\nThis development artifact is non-publishable, not headline eligible, and is not an independent external reproduction. Run `./reproduce.sh DEST`.\n",
            encoding="utf-8",
        )
        (temp / "reproduce.sh").write_text(
            '#!/bin/sh\nset -eu\ntest "$#" -eq 1 || { echo "usage: $0 DEST" >&2; exit 2; }\nuv run --locked mneme eval-public --reproduce-bundle "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" --out-dir "$1"\n',
            encoding="utf-8",
        )
        os.chmod(temp / "reproduce.sh", 0o755)
        required = REQUIRED + (("candidate-manifest.json",) if metadata["family"] == "qa" else ())
        _write_json(
            temp / "bundle-manifest.json",
            {"files": {name: _digest(temp / name) for name in required}, "version": 1},
        )
        temp.rename(destination)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def verify_bundle(bundle: Path | str) -> dict[str, Any]:
    root = Path(bundle)
    repro = root / REPRODUCIBILITY_MANIFEST_NAME
    if repro.exists() or repro.is_symlink():
        return _verify_reproducibility_bundle(root)
    if not root.is_dir() or root.is_symlink():
        raise BundleError("bundle must be a real directory, not a link")
    actual = {entry.name for entry in root.iterdir()}
    payload_files = REQUIRED + (("candidate-manifest.json",) if "candidate-manifest.json" in actual else ())
    expected = {*payload_files, "bundle-manifest.json"}
    if actual != expected:
        raise BundleError("inventory mismatch")
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise BundleError(f"links and non-files are forbidden: {entry.name}")
        if entry.resolve().parent != root.resolve():
            raise BundleError(f"path escapes bundle: {entry.name}")
    raw = b"".join((root / name).read_bytes() for name in sorted(actual))
    if SECRET.search(raw.decode("utf-8", errors="replace")):
        raise BundleError("secret-like material detected")
    manifest = _load_json(root / "bundle-manifest.json")
    if set(manifest.get("files", {})) != set(payload_files):
        raise BundleError("manifest inventory mismatch")
    for name, expected_digest in manifest["files"].items():
        if _digest(root / name) != expected_digest:
            raise BundleError(f"digest mismatch: {name}")
    benchmark, config, measured, build = (
        _load_json(root / "benchmark.json"),
        _load_json(root / "config.json"),
        _load_json(root / "metrics.json"),
        _load_json(root / "build.json"),
    )
    judge = _load_json(root / "judge.json")
    traces = [
        _parse_json(line, "traces.jsonl")
        for line in (root / "traces.jsonl").read_text().splitlines()
    ]
    trace_ids = [_trace_id(trace, family=config.get("family")) for trace in traces]
    if len(trace_ids) != len(set(trace_ids)):
        raise BundleError("duplicate trace IDs")
    family, method, profile = (
        config.get("family"),
        config.get("interval_method"),
        config.get("scoring_profile"),
    )
    if measured.get("trace_count") != len(traces):
        raise BundleError("trace/metric count drift")
    # M03's scored population is its as-of history queries, not its traces, so
    # `total` carries its own denominator and is pinned separately below, once
    # the benchmark it is derived from has been digest-anchored to the registry.
    if profile != "wmbs-m03-valid-time-v1" and measured.get("total") != len(traces):
        raise BundleError("trace/metric count drift")
    allowed_profile = _REGISTERED_SCORING_PROFILES.get(profile)
    if any(trace.get("scoring_family") != family for trace in traces):
        raise BundleError("metric families may not be blended")
    if family in {
        "deterministic-retrieval",
        "deterministic-action",
        "whole-memory-development",
    } and (
        judge.get("reader") is not None or judge.get("judge") is not None
    ):
        raise BundleError("deterministic families must not declare a reader or judge")
    if family == "qa" and not all(
        isinstance(judge.get(key), str) and judge[key].strip()
        for key in ("reader", "judge")
    ):
        raise BundleError("QA family must disclose its reader and judge")
    if (family == "qa") != ("candidate-manifest.json" in actual):
        raise BundleError("QA candidate manifest inventory mismatch")
    if allowed_profile != (family, method):
        raise BundleError("wrong interval-family metadata")
    metadata = benchmark.get("metadata", {})
    dataset_bytes = _canonical(benchmark.get("data"))
    if family == "deterministic-action":
        dataset_bytes = dataset_bytes.rstrip(b"\n")
    if hashlib.sha256(dataset_bytes).hexdigest() != metadata.get("dataset_sha256"):
        raise BundleError("benchmark custody digest mismatch")
    _verify_registry_anchor(metadata)
    if profile == "wmbs-m03-valid-time-v1":
        # The fixture is now digest-anchored to the registry, so its own shape
        # fixes the scored denominator exactly: one as-of history query per
        # (timeline history entry, seed). `total` is pinned to that count, not
        # merely exempted from the trace-count equality above.
        data = benchmark.get("data")
        timelines = data.get("timelines") if isinstance(data, dict) else None
        seeds = data.get("seeds") if isinstance(data, dict) else None
        if not isinstance(timelines, list) or not isinstance(seeds, list):
            raise BundleError("trace/metric count drift")
        expected_total = len(seeds) * sum(
            len(timeline.get("history") or []) if isinstance(timeline, dict) else 0
            for timeline in timelines
        )
        if measured.get("total") != expected_total:
            raise BundleError("trace/metric count drift")
    if build.get("system_seam") != metadata.get(
        "system_seam", "public-cli-subprocess"
    ):
        raise BundleError("build system seam does not match registry metadata")
    expected_config = {
        "family": metadata.get("family"),
        "interval_method": metadata.get("interval_method"),
        "scoring_profile": metadata.get("scoring_profile"),
        "suite": metadata.get("suite"),
    }
    if family == "qa":
        expected_config["interval_methods"] = metadata.get("interval_methods")
    if config != expected_config:
        raise BundleError("bundle config does not match canonical registry metadata")
    if measured.get("family") != family:
        raise BundleError("metrics/config family mismatch")
    if family == "qa":
        _verify_qa_custody(metadata, judge, benchmark.get("data"), traces, root / "candidate-manifest.json", measured, build)
    if profile == "smoke-hit-at-k-v1":
        if measured.get("interval", {}).get("method") != method:
            raise BundleError("wrong interval-family metadata")
        _verify_metrics(family, benchmark.get("data"), measured, traces)
    else:
        from eval.public.scoring import ScoringError, score_profile

        try:
            expected_metrics = score_profile(
                profile, _scoring_labels(benchmark.get("data")), traces
            )
        except (ScoringError, ValueError, TypeError, AttributeError, KeyError) as exc:
            raise BundleError(
                "generalized scoring profile recomputation failed"
            ) from exc
        if measured != expected_metrics:
            raise BundleError("metrics do not recompute from anchored scoring profile")
    if any(
        metadata.get(flag) is not False
        for flag in (
            "publishable",
            "pbpp_headline_eligible",
            "independent_external_reproduction",
        )
    ):
        raise BundleError("smoke publication flags must remain false")
    return {"family": family, "suite": metadata.get("suite"), "valid": True}


def reproduce_bundle(source: Path | str, destination: Path | str) -> dict[str, Any]:
    source_root = Path(source)
    repro = source_root / REPRODUCIBILITY_MANIFEST_NAME
    if repro.exists() or repro.is_symlink():
        return _reproduce_reproducibility_bundle(source_root, Path(destination))
    verify_bundle(source)
    custody = _load_json(Path(source) / "benchmark.json")
    from eval.public.runner import run_public_suite

    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    try:
        result = run_public_suite(
            custody["metadata"]["suite"],
            destination,
            benchmark_override=custody["data"],
            candidate_manifest_path=(Path(source) / "candidate-manifest.json") if custody["metadata"]["family"] == "qa" else None,
        )
        verify_bundle(destination)
        for name in _manifest_files(Path(source)):
            if (Path(source) / name).read_bytes() != (destination / name).read_bytes():
                raise BundleError(f"reproduction mismatch: {name}")
        return result
    except BaseException:
        if destination.is_dir():
            shutil.rmtree(destination)
        raise


def write_report(
    source: Path | str,
    reproduced: Path | str,
    report_output: Path | str,
    report_note: Path | str,
) -> dict[str, Any]:
    """Write a deterministic evidence report only for a matching reproduction."""
    source_root, reproduced_root = Path(source).resolve(), Path(reproduced).resolve()
    source_result, reproduced_result = (
        verify_bundle(source_root),
        verify_bundle(reproduced_root),
    )
    if source_result != reproduced_result:
        raise BundleError("source and reproduced bundle verification metadata mismatch")
    source_files = _manifest_files(source_root)
    if source_files != _manifest_files(reproduced_root):
        raise BundleError("source and reproduced bundle inventory mismatch")
    for name in source_files:
        if (source_root / name).read_bytes() != (reproduced_root / name).read_bytes():
            raise BundleError(f"source and reproduced bundle mismatch: {name}")
    output, note = Path(report_output), Path(report_note)
    if output.exists() or note.exists():
        raise FileExistsError("refusing to overwrite report output or note")
    git_sha = _git_sha()
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence = _report_evidence(source_root, reproduced_root)
    report = {
        "bindings": {
            "reproduced_bundle_manifest_sha256": _digest(
                reproduced_root / "bundle-manifest.json"
            ),
            "source_bundle_manifest_sha256": _digest(
                source_root / "bundle-manifest.json"
            ),
            **{
                f"{name.replace('.', '_')}_sha256": _digest(source_root / name)
                for name in ("benchmark.json", "metrics.json", "traces.jsonl")
            },
        },
        "git_sha": git_sha,
        "generated_at": generated_at,
        "evidence": evidence,
        "command": [
            "mneme",
            "eval-public",
            "--write-report",
            str(source_root),
            "--reproduced-bundle",
            str(reproduced_root),
            "--report-output",
            str(output.resolve()),
            "--report-note",
            str(note.resolve()),
        ],
        "publication": {
            "independent_external_reproduction": False,
            "pbpp_headline_eligible": False,
            "publishable": False,
        },
        "reproduced_bundle": str(reproduced_root),
        "source_bundle": str(source_root),
        "suite": source_result["suite"],
        "version": 1,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    note.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output, _canonical(report))
    report_digest = _digest(output)
    markdown = _render_report_note(report, report_digest)
    try:
        _atomic_write(note, markdown)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {
        "report": str(output.resolve()),
        "report_note": str(note.resolve()),
        "sha256": report_digest,
        "valid": True,
    }


def verify_report(report_path: Path | str, report_note: Path | str) -> dict[str, Any]:
    report_file, note_file = Path(report_path), Path(report_note)
    for path in (report_file, note_file):
        if path.is_symlink() or not path.is_file():
            raise BundleError("report and report note must be real files, not links")
    report = _load_json(report_file)
    if (
        set(report)
        != {
            "bindings",
            "command",
            "evidence",
            "generated_at",
            "git_sha",
            "publication",
            "reproduced_bundle",
            "source_bundle",
            "suite",
            "version",
        }
        or report["version"] != 1
    ):
        raise BundleError("invalid report schema")
    if len(report.get("git_sha", "")) != 40 or set(report["git_sha"]) - set(
        "0123456789abcdef"
    ):
        raise BundleError("invalid report git SHA")
    source, reproduced = (
        Path(report["source_bundle"]),
        Path(report["reproduced_bundle"]),
    )
    source_result, reproduced_result = verify_bundle(source), verify_bundle(reproduced)
    if source_result != reproduced_result or source_result["suite"] != report["suite"]:
        raise BundleError("report suite binding mismatch")
    expected = {
        "reproduced_bundle_manifest_sha256": _digest(
            reproduced / "bundle-manifest.json"
        ),
        "source_bundle_manifest_sha256": _digest(source / "bundle-manifest.json"),
        **{
            f"{name.replace('.', '_')}_sha256": _digest(source / name)
            for name in ("benchmark.json", "metrics.json", "traces.jsonl")
        },
    }
    if report.get("bindings") != expected:
        raise BundleError("report cryptographic binding mismatch")
    try:
        generated_at = datetime.fromisoformat(
            report["generated_at"].replace("Z", "+00:00")
        )
    except (AttributeError, ValueError) as exc:
        raise BundleError("invalid report UTC timestamp") from exc
    if not report["generated_at"].endswith("Z") or generated_at.tzinfo != UTC:
        raise BundleError("invalid report UTC timestamp")
    expected_command = [
        "mneme",
        "eval-public",
        "--write-report",
        str(source.resolve()),
        "--reproduced-bundle",
        str(reproduced.resolve()),
        "--report-output",
        str(report_file.resolve()),
        "--report-note",
        str(note_file.resolve()),
    ]
    if report.get("command") != expected_command:
        raise BundleError("report command provenance mismatch")
    if report.get("evidence") != _report_evidence(
        source.resolve(), reproduced.resolve()
    ):
        raise BundleError("report evidence projection mismatch")
    source_files = _manifest_files(source)
    if source_files != _manifest_files(reproduced):
        raise BundleError("reported reproduction inventory mismatch")
    for name in source_files:
        if (source / name).read_bytes() != (reproduced / name).read_bytes():
            raise BundleError(f"reported reproduction mismatch: {name}")
    if any(
        report.get("publication", {}).get(flag) is not False
        for flag in (
            "publishable",
            "pbpp_headline_eligible",
            "independent_external_reproduction",
        )
    ):
        raise BundleError("report publication flags must remain false")
    note_bytes = note_file.read_bytes()
    if note_bytes != _render_report_note(report, _digest(report_file)):
        raise BundleError("report note binding is not the exact canonical projection")
    note = note_bytes.decode("utf-8")
    for value in (
        _digest(report_file),
        expected["source_bundle_manifest_sha256"],
        expected["reproduced_bundle_manifest_sha256"],
        report["git_sha"],
    ):
        if f"`{value}`" not in note:
            raise BundleError("report note binding mismatch")
    for projection in (
        json.dumps(
            {
                "assets": report["evidence"]["assets"],
                "benchmark_metadata": report["evidence"]["benchmark_metadata"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        json.dumps(
            report["evidence"]["metrics"], sort_keys=True, separators=(",", ":")
        ),
        json.dumps(
            {
                "command": report["command"],
                "provenance": report["evidence"]["provenance"],
                "reproduction": report["evidence"]["reproduction"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        f"Eligible records: `{report['evidence']['counts']['eligible']}`",
        f"Excluded records: `{report['evidence']['counts']['excluded']}`",
        f"Generated at (UTC): `{report['generated_at']}`",
    ):
        if projection not in note:
            raise BundleError("report note evidence projection mismatch")
    return {
        "report": str(report_file.resolve()),
        "report_note": str(note_file.resolve()),
        "sha256": _digest(report_file),
        "valid": True,
    }


def _report_evidence(source: Path, reproduced: Path) -> dict[str, Any]:
    benchmark = _load_json(source / "benchmark.json")
    build = _load_json(source / "build.json")
    metrics = _load_json(source / "metrics.json")
    metadata = benchmark.get("metadata", {})
    data = benchmark.get("data", {})
    questions = data.get("questions", []) if isinstance(data, dict) else []
    trace_count = metrics.get("trace_count")
    eligible = metadata.get(
        "eligible_count", len(questions) if isinstance(questions, list) else trace_count
    )
    excluded = metadata.get("excluded_count", 0)
    if not isinstance(eligible, int) or isinstance(eligible, bool) or eligible < 0:
        raise BundleError("invalid eligible count metadata")
    if not isinstance(excluded, int) or isinstance(excluded, bool) or excluded < 0:
        raise BundleError("invalid excluded count metadata")
    assets = metadata.get("assets")
    if assets is None:
        assets = [
            {
                key: metadata.get(key)
                for key in ("dataset_sha256", "license", "revision", "split_role")
            }
        ]
    if not isinstance(assets, list) or not assets:
        raise BundleError("report requires benchmark asset metadata")
    return {
        "assets": assets,
        "benchmark_metadata": metadata,
        "counts": {"eligible": eligible, "excluded": excluded, "traces": trace_count},
        "metrics": metrics,
        "provenance": {
            "build": build,
            "source_bundle": str(source.resolve()),
            "system_seam": build.get("system_seam"),
        },
        "reproduction": {
            "matched_files": list(_manifest_files(source)),
            "reproduced_bundle": str(reproduced.resolve()),
            "verified": True,
        },
    }


def _render_report_note(report: dict[str, Any], report_digest: str) -> bytes:
    evidence = report["evidence"]
    return (
        f"# Public evaluation report: {report['suite']}\n\n"
        "This report is non-publishable, not PBPP headline eligible, and is not an independent external reproduction.\n\n"
        f"- External report SHA-256: `{report_digest}`\n"
        f"- Source bundle manifest SHA-256: `{report['bindings']['source_bundle_manifest_sha256']}`\n"
        f"- Reproduced bundle manifest SHA-256: `{report['bindings']['reproduced_bundle_manifest_sha256']}`\n"
        f"- Git SHA: `{report['git_sha']}`\n"
        f"- Generated at (UTC): `{report['generated_at']}`\n\n"
        "## Assets and benchmark metadata\n\n"
        f"```json\n{json.dumps({'assets': evidence['assets'], 'benchmark_metadata': evidence['benchmark_metadata']}, sort_keys=True, separators=(',', ':'))}\n```\n\n"
        f"- Eligible records: `{evidence['counts']['eligible']}`\n"
        f"- Excluded records: `{evidence['counts']['excluded']}`\n\n"
        "## Metrics\n\n"
        f"```json\n{json.dumps(evidence['metrics'], sort_keys=True, separators=(',', ':'))}\n```\n\n"
        "## Reproduction and provenance\n\n"
        f"```json\n{json.dumps({'command': report['command'], 'provenance': evidence['provenance'], 'reproduction': evidence['reproduction']}, sort_keys=True, separators=(',', ':'))}\n```\n"
    ).encode()


def _scoring_labels(benchmark: Any) -> list[dict[str, Any]]:
    if not isinstance(benchmark, dict):
        raise BundleError("scoring profile benchmark is missing")
    if isinstance(benchmark.get("cases"), list):
        if benchmark.get("schema_id") == "wmbs-m10-development/fixture/0.1":
            artifact = benchmark.get("calibration_artifact")
            return [
                {
                    "calibration_artifact": artifact,
                    "case": case,
                    "case_id": case.get("case_id"),
                    "fixture": benchmark,
                }
                for case in benchmark["cases"]
                if case.get("partition") == "scored"
            ]
        if benchmark.get("benchmark") in {"pm-bench", "triggerbench"}:
            return [
                {
                    "case_id": case.get("case_id"),
                    "step_id": step.get("step_id"),
                    "category": case.get("category"),
                    "expected_due_action_ids": step.get("expected_due_action_ids"),
                    "operating_point_id": benchmark.get("operating_point_id"),
                    "operating_point_config": benchmark.get("operating_point_config"),
                }
                for case in benchmark["cases"]
                for step in case.get("steps", [])
            ]
        if benchmark.get("suite") == "working-memory-action-v1":
            return [
                {
                    "case_id": case.get("case_id"),
                    "category": case.get("category"),
                    "expected_action_id": case.get("expected_action_id"),
                    "expected_abstain": case.get("expected_abstain"),
                    "seed": benchmark.get("seed"),
                }
                for case in benchmark["cases"]
            ]
        raise BundleError("unknown case-based benchmark schema")
    if benchmark.get("schema_id") == "wmbs-m01-fixture-v1":
        return [{"case_id": "M01", "fixture": benchmark}]
    if benchmark.get("schema_id") == "wmbs-m03-valid-time-development/fixture/0.1":
        return [{"case_id": "M03", "fixture": benchmark}]
    if benchmark.get("schema_id") == "wmbs-m05-provenance-development/fixture/0.1":
        return [{"case_id": "M05", "fixture": benchmark}]
    if not isinstance(benchmark.get("questions"), list):
        raise BundleError("scoring profile benchmark questions are missing")
    labels = []
    for question in benchmark["questions"]:
        if not isinstance(question, dict):
            raise BundleError("scoring profile question schema is invalid")
        label: dict[str, Any] = {"question_id": question.get("question_id")}
        present_golds = [
            question[key]
            for key in (
                "gold_references",
                "answer_session_ids",
                "gold_doc_ids",
                "gold_passage_ids",
            )
            if key in question
        ]
        if len(present_golds) > 1 and any(
            value != present_golds[0] for value in present_golds[1:]
        ):
            raise BundleError("conflicting benchmark gold fields")
        gold = question.get(
            "gold_references",
            question.get(
                "answer_session_ids",
                question.get("gold_doc_ids", question.get("gold_passage_ids")),
            ),
        )
        if gold is not None:
            label["gold_references"] = gold
        if "answers" in question:
            label["answers"] = question["answers"]
        labels.append(label)
    return labels


def _trace_id(trace: dict[str, Any], *, family: Any) -> tuple[Any, ...]:
    if family in {"deterministic-action", "whole-memory-development"}:
        case_id, step_id = trace.get("case_id"), trace.get("step_id")
        if not isinstance(case_id, str) or not case_id or (
            step_id is not None and (not isinstance(step_id, str) or not step_id)
        ):
            raise BundleError("missing deterministic-action trace ID")
        return (case_id,) if step_id is None else (case_id, step_id)
    question_id = trace.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        raise BundleError("missing question ID")
    return (question_id,)


def _verify_qa_custody(
    metadata: dict[str, Any],
    judge: dict[str, Any],
    benchmark: Any,
    traces: list[dict[str, Any]],
    candidate_path: Path,
    measured: dict[str, Any],
    build: dict[str, Any],
) -> None:
    from eval.public.runner import load_qa_protocol, qa_protocol_digests, require_clean_candidate_checkout, validate_candidate_manifest
    from mnemosyne.providers.extractive_decomposer import (
        disclosure as decomposer_disclosure,
    )
    from mnemosyne.providers.grounded_protocol import PROMPT_BUNDLES, role_digests

    protocol = load_qa_protocol()
    custody = metadata.get("reader_custody")
    if not isinstance(custody, dict) or judge.get("custody") != custody:
        raise BundleError("QA reader custody mismatch")
    if custody.get("protocol_version") != protocol["version"]:
        raise BundleError("QA protocol version mismatch")
    if custody.get("decomposer") != protocol["decomposer"]:
        raise BundleError("QA decomposer custody does not match preregistration")
    reader = custody.get("reader")
    if not isinstance(reader, dict) or set(reader) != {"model_content_sha256", "model_revision", "name", "provider", "selector"}:
        raise BundleError("QA reader model custody is incomplete")
    expected_reader = {"model_revision": protocol["model"]["selector"], "name": "grounded-reader", "provider": protocol["model"]["provider"], "selector": protocol["model"]["selector"]}
    if any(reader.get(key) != value for key, value in expected_reader.items()):
        raise BundleError("QA reader provider and selector must match preregistration")
    _require_sha256(reader.get("model_content_sha256"), "reader model content")
    prompt = custody.get("prompt")
    if not isinstance(prompt, dict) or set(prompt) != {"aggregate_sha256", "roles", "serializer_sha256"}:
        raise BundleError("QA prompt custody is incomplete")
    _require_sha256(prompt.get("aggregate_sha256"), "aggregate prompt custody")
    _require_sha256(prompt.get("serializer_sha256"), "evidence serializer")
    expected_digests = qa_protocol_digests(protocol)
    if prompt != {
        "aggregate_sha256": expected_digests["prompt_sha256"],
        "roles": {
            role: {"template_sha256": role_digests(role)["prompt_sha256"]}
            for role in sorted(PROMPT_BUNDLES)
        },
        "serializer_sha256": expected_digests["serializer_sha256"],
    }:
        raise BundleError("QA prompt custody does not match preregistration")
    if custody.get("decoding") != protocol["decoding"]:
        raise BundleError("QA decoding config does not match preregistration")
    if custody.get("evidence_budget") != protocol["evidence_budget"]:
        raise BundleError("QA evidence budget does not match preregistration")
    if custody.get("abstention") != protocol["abstention"]:
        raise BundleError("QA abstention rule does not match preregistration")
    if custody.get("split_role") not in {"frozen-internal", "held-out-test", "held-out-validation"}:
        raise BundleError("QA split declaration may not be development")
    if custody.get("transport_retries") != protocol["held_out_policy"]["transport_retries"]:
        raise BundleError("QA transport retry count does not match preregistration")
    _require_sha256(custody.get("candidate_manifest_sha256"), "candidate manifest")
    candidate = _load_json(candidate_path)
    if not isinstance(build.get("candidate_git_sha"), str):
        raise BundleError("QA build git SHA is missing")
    if build["candidate_git_sha"] != _git_sha():
        raise BundleError("QA build git SHA does not match the verifying checkout")
    try:
        require_clean_candidate_checkout(build["candidate_git_sha"])
    except ValueError as exc:
        raise BundleError("QA candidate checkout is not clean") from exc
    try:
        validate_candidate_manifest(candidate, expected_git_sha=build["candidate_git_sha"])
    except ValueError as exc:
        raise BundleError("embedded candidate manifest schema mismatch") from exc
    if candidate.get("git_sha") != custody.get("candidate_git_sha"):
        raise BundleError("candidate, build, and custody git SHA mismatch")
    if _digest(candidate_path) != custody["candidate_manifest_sha256"]:
        raise BundleError("embedded candidate manifest digest mismatch")
    if candidate.get("model_content_sha256") != reader["model_content_sha256"]:
        raise BundleError("candidate manifest model digest mismatch")
    expected_trace_reader = {
        "query_decomposer": decomposer_disclosure(),
        "grounded_reader": {
            "role": "grounded_reader",
            "model": protocol["model"]["selector"],
            "model_content_digest": reader["model_content_sha256"],
            **role_digests("grounded_reader"),
            "decoding_options": protocol["decoding"],
        },
    }
    if metadata.get("interval_methods") != protocol["interval_methods"]:
        raise BundleError("QA mixed interval declaration mismatch")
    intervals = measured.get("intervals", {})
    if {key: value.get("method") for key, value in intervals.items()} != protocol["interval_methods"]:
        raise BundleError("QA mixed interval metadata mismatch")
    labels = _scoring_labels(benchmark)
    if any(not isinstance(label.get("answers"), list) or not label["answers"] for label in labels):
        raise BundleError("QA benchmark answer labels are missing")
    content_by_cid = _benchmark_content_by_cid(benchmark)
    for trace in traces:
        if any(key in trace for key in ("score", "exact_match", "token_f1")):
            raise BundleError("reader traces may not self-score")
        trace_reader = trace.get("reader")
        if (
            not isinstance(trace_reader, dict)
            or set(trace_reader)
            not in ({"query_decomposer"}, {"query_decomposer", "grounded_reader"})
            or any(
                trace_reader.get(role) != expected_trace_reader[role]
                for role in trace_reader
            )
        ):
            raise BundleError("QA trace reader disclosure does not match preregistration")
        answer, claims, abstained = trace.get("answer"), trace.get("claims"), trace.get("abstained")
        if "authorized_evidence_cids" in trace:
            raise BundleError("QA trace may not self-attest an authorized CID list")
        authorized = _authorized_cids_from_hops(
            trace.get("authorized_retrieval_hops"),
            benchmark,
            protocol["evidence_budget"],
        )
        if authorized and "grounded_reader" not in trace_reader:
            raise BundleError("QA trace reader disclosure is incomplete for authorized evidence")
        expected_fingerprint = hashlib.sha256(_canonical(sorted(authorized))).hexdigest()
        if trace.get("authorized_evidence_fingerprint") != expected_fingerprint:
            raise BundleError("QA authorized evidence fingerprint mismatch")
        if abstained is True:
            if answer != "" or claims != []:
                raise BundleError("QA abstention must use the canonical empty output")
            continue
        if abstained is not False or not isinstance(answer, str) or not answer or not isinstance(claims, list) or not claims:
            raise BundleError("non-abstained QA output requires answer and claims")
        if set(trace_reader) != {"query_decomposer", "grounded_reader"}:
            raise BundleError("non-abstained QA output requires complete reader disclosure")
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) != {"evidence_cids", "spans", "text"}:
                raise BundleError("QA claim schema is invalid")
            if not isinstance(claim["text"], str) or not claim["text"].strip() or not isinstance(claim["evidence_cids"], list) or not claim["evidence_cids"] or not isinstance(claim["spans"], list) or not 1 <= len(claim["spans"]) <= 3:
                raise BundleError("every QA claim requires citations")
            if any(not isinstance(cid, str) or not cid for cid in claim["evidence_cids"]):
                raise BundleError("every QA claim requires valid citations")
            if len(claim["evidence_cids"]) != len(set(claim["evidence_cids"])) or not set(claim["evidence_cids"]) <= set(authorized):
                raise BundleError("QA claim citations must be a unique authorized subset")
            rendered_spans: list[str] = []
            occupied: dict[str, list[tuple[int, int]]] = {}
            span_cids: list[str] = []
            for span in claim["spans"]:
                if not isinstance(span, dict) or set(span) != {"cid", "end", "slice_sha256", "start"}:
                    raise BundleError("QA claim span schema is invalid")
                cid, start, end = span["cid"], span["start"], span["end"]
                if not isinstance(cid, str) or cid not in authorized or cid not in content_by_cid or not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
                    raise BundleError("QA claim span provenance is invalid")
                content = content_by_cid[cid]
                if not 0 <= start < end <= len(content):
                    raise BundleError("QA claim span offsets are invalid")
                ranges = occupied.setdefault(cid, [])
                if any(start < right and left < end for left, right in ranges):
                    raise BundleError("QA claim spans overlap")
                ranges.append((start, end))
                selected = content[start:end]
                if span["slice_sha256"] != hashlib.sha256(selected.encode("utf-8")).hexdigest():
                    raise BundleError("QA claim span digest mismatch")
                rendered_spans.append(selected)
                if cid not in span_cids:
                    span_cids.append(cid)
            if claim["evidence_cids"] != span_cids:
                raise BundleError("QA claim citations do not match ordered spans")
            if claim["text"] != " ".join(rendered_spans):
                raise BundleError("QA claim text does not match evidence spans")
        rendered = "\n".join(claim["text"].strip() for claim in claims)
        if answer != rendered:
            raise BundleError("QA answer must render deterministically from ordered claims")


def _benchmark_content_by_cid(benchmark: Any) -> dict[str, str]:
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("corpus"), list):
        raise BundleError("QA benchmark corpus is missing")
    result: dict[str, str] = {}
    for record in benchmark["corpus"]:
        if not isinstance(record, dict):
            raise BundleError("QA benchmark corpus custody is incomplete")
        cid, content, capture = record.get("doc_id"), record.get("content"), record.get("capture")
        if not isinstance(cid, str) or not cid or cid in result or not isinstance(content, str) or not content or not isinstance(capture, dict) or capture.get("content") != content:
            raise BundleError("QA benchmark CID/content mapping is invalid")
        result[cid] = content
    return result


def _authorized_cids_from_hops(
    value: Any,
    benchmark: Any,
    evidence_budget: Any,
) -> list[str]:
    if (
        not isinstance(evidence_budget, dict)
        or set(evidence_budget)
        != {"max_characters", "max_hops", "max_records"}
        or any(
            not isinstance(evidence_budget.get(key), int)
            or isinstance(evidence_budget[key], bool)
            or evidence_budget[key] <= 0
            for key in evidence_budget
        )
    ):
        raise BundleError("QA evidence budget is invalid")
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("corpus"), list):
        raise BundleError("QA benchmark corpus is missing")
    anchored: dict[str, dict[str, Any]] = {}
    for record in benchmark["corpus"]:
        if not isinstance(record, dict) or set(record) < {"capture", "content", "doc_id", "source_identity"}:
            raise BundleError("QA benchmark corpus custody is incomplete")
        if record["capture"].get("content") != record["content"] or record["capture"].get("source_identity") != record["source_identity"]:
            raise BundleError("QA benchmark capture mapping is inconsistent")
        anchored[record["doc_id"]] = record["capture"]
    if not isinstance(value, list) or not value:
        raise BundleError("QA trace requires retained authorized retrieval hops")
    if len(value) > evidence_budget["max_hops"]:
        raise BundleError("QA authorized retrieval exceeds the hop budget")
    hops: set[int] = set()
    cids: list[str] = []
    content_characters = 0
    for hop in value:
        if (
            not isinstance(hop, dict)
            or set(hop) != {"hop", "rows"}
            or not isinstance(hop["hop"], int)
            or isinstance(hop["hop"], bool)
            or hop["hop"] < 0
            or hop["hop"] in hops
        ):
            raise BundleError("QA authorized retrieval hop schema is invalid")
        hops.add(hop["hop"])
        if not isinstance(hop["rows"], list):
            raise BundleError("QA authorized retrieval rows are invalid")
        for row in hop["rows"]:
            if not isinstance(row, dict) or set(row) != {"capture", "cid"}:
                raise BundleError("QA authorized retrieval row schema is invalid")
            if not isinstance(row.get("cid"), str) or not row["cid"] or not isinstance(row.get("capture"), dict):
                raise BundleError("QA authorized retrieval provenance is invalid")
            recomputed = _engine_evidence_cid(row["capture"])
            if row["cid"] != recomputed or anchored.get(row["cid"]) != row["capture"]:
                raise BundleError("QA authorized retrieval row does not match anchored corpus custody")
            cids.append(row["cid"])
            content_characters += len(row["capture"]["content"])
            if len(cids) > evidence_budget["max_records"]:
                raise BundleError("QA authorized retrieval exceeds the record budget")
            if content_characters > evidence_budget["max_characters"]:
                raise BundleError("QA authorized retrieval exceeds the character budget")
    if [hop["hop"] for hop in value] != list(range(len(value))):
        raise BundleError("QA authorized retrieval hops must be ordered and contiguous")
    if len(cids) != len(set(cids)):
        raise BundleError("QA authorized retrieval rows contain duplicate CIDs")
    return cids


def _engine_evidence_cid(capture: dict[str, Any]) -> str:
    from eval.public.custody import capture_cid

    required = {"actor", "content", "content_pointer", "modality", "sensitivity", "source_identity", "source_type", "tenant_id", "user_id"}
    if set(capture) != required:
        raise BundleError("QA capture envelope schema is incomplete")
    if not all(isinstance(capture.get(key), str) and capture[key] for key in ("actor", "content", "modality", "source_identity", "source_type", "tenant_id", "user_id")):
        raise BundleError("QA capture envelope values are invalid")
    if capture["content_pointer"] is not None or not isinstance(capture["sensitivity"], int) or isinstance(capture["sensitivity"], bool):
        raise BundleError("QA capture envelope values are invalid")
    return capture_cid(capture)


def _manifest_files(root: Path) -> tuple[str, ...]:
    manifest = _load_json(root / "bundle-manifest.json")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BundleError("manifest inventory mismatch")
    return tuple(sorted(files))


def _reject_symlink_path(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        if current.is_symlink():
            raise BundleError("candidate manifest path components must not be symlinks")


def _require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise BundleError(f"QA {label} digest must be exact SHA-256")


def _verify_registry_anchor(metadata: dict[str, Any]) -> None:
    from eval.public.runner import load_registry

    suite_name = metadata.get("suite")
    registry = load_registry()
    if suite_name not in registry:
        raise BundleError("suite has no canonical registry anchor")
    canonical = registry[suite_name]
    anchored = (
        "adapter",
        "dataset_sha256",
        "family",
        "independent_external_reproduction",
        "interval_method",
        "license",
        "pbpp_headline_eligible",
        "publishable",
        "revision",
        "split_role",
        "scoring_profile",
        "qa_protocol_version",
        "interval_methods",
        "assets",
        "fixture",
        "headline_eligible",
        "upstream_comparable",
        "admission_state",
        "track_kind",
        "system_seam",
    )
    if any(metadata.get(key) != canonical.get(key) for key in anchored):
        raise BundleError("bundle metadata does not match canonical registry anchor")


def _verify_metrics(
    family: str,
    benchmark: Any,
    measured: dict[str, Any],
    traces: list[dict[str, Any]],
) -> None:
    if family != "deterministic-retrieval":
        return
    from eval.harness.metrics import wilson_interval

    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("k"), int):
        raise BundleError("retrieval benchmark is missing k")
    questions = benchmark.get("questions")
    corpus = benchmark.get("corpus")
    if not isinstance(questions, list) or not isinstance(corpus, list):
        raise BundleError("retrieval benchmark schema is invalid")
    gold_by_question = {
        question.get("question_id"): question.get("gold_doc_ids")
        for question in questions
    }
    doc_ids = {document.get("doc_id") for document in corpus}
    if (
        None in gold_by_question
        or None in doc_ids
        or set(gold_by_question) != {trace.get("question_id") for trace in traces}
    ):
        raise BundleError("traces do not match anchored benchmark questions")
    for trace in traces:
        question_id = trace["question_id"]
        if trace.get("gold_references") != gold_by_question[question_id]:
            raise BundleError("trace gold does not match anchored benchmark")
        stored = trace.get("stored_records")
        ranked = trace.get("ranked_retrieved_hits")
        if not isinstance(stored, list) or set(stored) != doc_ids:
            raise BundleError("stored records do not match anchored benchmark corpus")
        if not isinstance(ranked, list) or any(item not in doc_ids for item in ranked):
            raise BundleError("retrieved hit is outside anchored benchmark corpus")
        if trace.get("answer") is not None and trace.get("answer") not in doc_ids:
            raise BundleError("answer is outside anchored benchmark corpus")
    if measured.get("metric") != "hit_at_k":
        raise BundleError("deterministic retrieval metric must be hit_at_k")
    k = benchmark["k"]
    successes = sum(
        bool(
            set(trace["ranked_retrieved_hits"][:k])
            & set(gold_by_question[trace["question_id"]])
        )
        for trace in traces
    )
    expected = wilson_interval(successes, len(traces)).as_dict()
    interval = measured.get("interval", {})
    recomputed = {
        "family": family,
        "successes": successes,
        "total": len(traces),
        "trace_count": len(traces),
        "value": expected["point"],
        "interval": {
            "confidence": 0.95,
            "high": expected["ci_high"],
            "low": expected["ci_low"],
            "method": expected["ci_method"],
        },
    }
    for key, value in recomputed.items():
        if key == "interval":
            if any(
                interval.get(nested) != expected_value
                for nested, expected_value in value.items()
            ):
                raise BundleError("metrics do not recompute from traces")
        elif measured.get(key) != value:
            raise BundleError("metrics do not recompute from traces")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical(value))


def _canonical(value: Any) -> bytes:
    _reject_non_finite(value)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _load_json(path: Path) -> Any:
    return _parse_json(path.read_text(encoding="utf-8"), path.name)


def _parse_json(raw: str, label: str) -> Any:
    try:
        value = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise BundleError(f"invalid JSON in {label}") from exc
    _reject_non_finite(value)
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise BundleError("non-finite number")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_non_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_non_finite(nested)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = nested
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _git_sha() -> str:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    sha = result.stdout.strip()
    if len(sha) != 40 or set(sha) - set("0123456789abcdef"):
        raise BundleError("could not resolve an exact git SHA")
    return sha
