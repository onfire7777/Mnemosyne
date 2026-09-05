"""Canonical public benchmark bundle custody, verification, and reproduction."""

from __future__ import annotations

import codecs
import errno
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AIza[A-Za-z0-9_-]{35}|AKIA[A-Z0-9]{16}|"
    r"sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"(?i:bearer|basic)\s+[A-Za-z0-9._~+/-]{20,}={0,2}|"
    r"[A-Za-z][A-Za-z0-9+.-]{0,31}://"
    r"[^/\s:@]{1,256}:[^/\s@]{1,256}@|"
    r"-----(?:BEGIN|END) [A-Z ]*PRIVATE KEY-----)"
)
SECRET_BYTES = re.compile(SECRET.pattern.encode("ascii"))
_SECRET_SCAN_CHUNK_SIZE = 1024 * 1024
# Longer than the maximum bounded credential-URL match so a match cannot be
# split across adjacent streaming scan windows.
_SECRET_SCAN_OVERLAP = 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 4
_UNSAFE_MODE_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}"
)
_REQUIRED_MEDIA_TYPES = {
    "README.md": "text/markdown",
    "ledger-public.pem": "application/x-pem-file",
    "independent-public.pem": "application/x-pem-file",
    "ledger.jsonl": "application/x-ndjson",
    "independent-ledger.jsonl": "application/x-ndjson",
    "traces.jsonl": "application/x-ndjson",
    "ledger.jsonl.lock": "text/plain",
    "independent-ledger.jsonl.lock": "text/plain",
    "reproduce.sh": "text/x-shellscript",
    "uv.lock": "text/plain",
}
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
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


class BundleError(ValueError):
    """Bundle failed closed under the public custody contract."""


REPRODUCIBILITY_SCHEMA_VERSION = "mnemosyne.reproducibility-bundle/v1"
REPRODUCTION_ARGV = (
    "uv",
    "run",
    "--locked",
    "--isolated",
    "mneme",
    "eval-public",
    "--reproduce-bundle",
    "BUNDLE",
    "--out-dir",
    "DEST",
)
_REPRO_TOP_LEVEL = {
    "schema_version",
    "result_ref",
    "inputs",
    "artifacts",
    "run",
    "metrics",
    "disclosures",
    "reproduction",
}
_REPRO_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REPRO_COMMIT = re.compile(r"[0-9a-f]{40}")
_CREDENTIAL_ENV_MARKERS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PRIVATE_KEY",
    "API_KEY",
    "ACCESS_KEY",
    "CREDENTIAL",
    "AUTHORIZATION",
)
_CREDENTIAL_ENV_NAMES = {
    "AWS_PROFILE",
    "DATABASE_URL",
    "DOCKER_CONFIG",
    "KUBECONFIG",
    "NETRC",
    "PGPASSFILE",
    "REDIS_URL",
    "SSH_AUTH_SOCK",
}
_FIXED_REPRODUCTION_ENV = {"UV_OFFLINE", "UV_RUN_RECURSION_DEPTH", "LC_ALL", "TZ"}
_SAFE_DECLARED_PYTHON_ENV = {"PYTHONHASHSEED", "PYTHONUTF8", "PYTHONIOENCODING"}
_INFLUENTIAL_ENV_PREFIXES = ("PYTHON", "PIP_", "UV_", "DYLD_", "GIT_")
_INFLUENTIAL_ENV_NAMES = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}


def _closed_object(
    value: object, required: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise BundleError(f"{label} must be an object")
    missing = sorted(required - value.keys())
    if missing:
        raise BundleError(f"{label} missing field: {missing[0]}")
    unknown = sorted(value.keys() - required)
    if unknown:
        raise BundleError(f"{label} unknown field: {unknown[0]}")
    return value


def _repro_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or _REPRO_DIGEST.fullmatch(value) is None:
        raise BundleError(f"{label} must be a canonical sha256 digest")


def _repro_nonempty(value: object, label: str, *, maximum: int = 512) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BundleError(f"{label} must be a bounded non-empty string")


def _repro_finite(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    containers: set[int] = set()
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > 100_000 or depth > 64:
            raise BundleError("reproducibility manifest exceeds structural bounds")
        if isinstance(current, float) and not math.isfinite(current):
            raise BundleError("reproducibility manifest numbers must be finite")
        if isinstance(current, str) and SECRET.search(current):
            raise BundleError("secret-like material detected in manifest")
        if isinstance(current, (dict, list)):
            identity = id(current)
            if identity in containers:
                raise BundleError("reproducibility manifest contains a cycle")
            containers.add(identity)
            if isinstance(current, dict):
                if any(
                    isinstance(key, str) and SECRET.search(key) for key in current
                ):
                    raise BundleError("secret-like material detected in manifest")
                nested = current.values()
            else:
                nested = current
            stack.extend((item, depth + 1) for item in nested)


def _repro_relative_path(value: object) -> str:
    parts = value.split("/") if isinstance(value, str) else []
    try:
        encoded_parts = [part.encode("utf-8") for part in parts]
    except UnicodeEncodeError as exc:
        raise BundleError("inventory path must be a normalized relative path") from exc
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or unicodedata.normalize("NFC", value) != value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or re.match(r"[A-Za-z]:", value) is not None
        or any(part in {"", ".", ".."} for part in parts)
        or any(len(part) > 255 for part in encoded_parts)
        or any(part.endswith((" ", ".")) for part in parts)
        or any(
            any(
                ord(character) < 32 or character in '<>:"|?*'
                for character in part
            )
            for part in parts
        )
        or any(
            part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in parts
        )
    ):
        raise BundleError("inventory path must be a normalized relative path")
    return value


def _portable_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _credential_environment_name(name: str) -> bool:
    normalized = name.upper()
    return normalized in _CREDENTIAL_ENV_NAMES or any(
        marker in normalized for marker in _CREDENTIAL_ENV_MARKERS
    )


def _undeclared_influential_environment_name(
    name: str, declared: set[str]
) -> bool:
    normalized = name.upper()
    if normalized in declared or normalized in _FIXED_REPRODUCTION_ENV:
        return False
    return normalized in _INFLUENTIAL_ENV_NAMES or normalized.startswith(
        _INFLUENTIAL_ENV_PREFIXES
    )


def _forbidden_declared_environment_name(name: str) -> bool:
    normalized = name.upper()
    if normalized in _FIXED_REPRODUCTION_ENV or normalized in _INFLUENTIAL_ENV_NAMES:
        return True
    if normalized.startswith(("PIP_", "UV_", "DYLD_", "GIT_")):
        return True
    return normalized.startswith("PYTHON") and normalized not in _SAFE_DECLARED_PYTHON_ENV


def validate_reproducibility_manifest(payload: object) -> dict[str, Any]:
    """Validate the closed, additive REPRO-001 manifest contract.

    This validates untrusted metadata only. It grants no publication, neutrality,
    certification, or independent-reproduction status.
    """
    _repro_finite(payload)
    manifest = _closed_object(payload, _REPRO_TOP_LEVEL, "manifest")
    if manifest["schema_version"] != REPRODUCIBILITY_SCHEMA_VERSION:
        raise BundleError("unsupported reproducibility manifest version")

    result = _closed_object(
        manifest["result_ref"],
        {"record_id", "result_digest", "ledger_entry_digest", "track_kind", "lineage"},
        "result reference",
    )
    _repro_nonempty(result["record_id"], "result record ID", maximum=256)
    _repro_digest(result["result_digest"], "result digest")
    _repro_digest(result["ledger_entry_digest"], "ledger entry digest")
    track_kind = result["track_kind"]
    if track_kind not in {
        "OFFICIAL-UPSTREAM",
        "ENHANCED-SUCCESSOR",
        "DEVELOPMENT",
    }:
        raise BundleError("result track kind is unsupported")
    lineage = result["lineage"]
    if track_kind == "DEVELOPMENT":
        _closed_object(lineage, set(), "development lineage")
    elif track_kind == "OFFICIAL-UPSTREAM":
        lineage = _closed_object(lineage, {"fidelity"}, "official lineage")
        fidelity_fields = {
            "upstream_protocol_digest",
            "dataset_digest",
            "split_digest",
            "preprocessing_digest",
            "scorer_digest",
            "environment_digest",
            "revision_digest",
        }
        fidelity = _closed_object(
            lineage["fidelity"], fidelity_fields, "official fidelity"
        )
        for field in fidelity_fields:
            _repro_digest(fidelity[field], field.replace("_", " "))
    else:
        lineage = _closed_object(
            lineage,
            {
                "parent_official_record_id",
                "parent_construct_digest",
                "difference_manifest_digest",
            },
            "successor lineage",
        )
        _repro_nonempty(
            lineage["parent_official_record_id"],
            "parent official record ID",
            maximum=256,
        )
        _repro_digest(lineage["parent_construct_digest"], "parent construct")
        _repro_digest(lineage["difference_manifest_digest"], "difference manifest")

    input_fields = {
        "benchmark_manifest_digest",
        "dataset_manifest_digest",
        "fixture_manifest_digest",
        "generator_manifest_digest",
        "adapter_manifest_digest",
        "scorer_manifest_digest",
        "baseline_manifest_digest",
        "judge_manifest_digest",
        "prompt_manifest_digest",
    }
    inputs = _closed_object(manifest["inputs"], input_fields, "inputs")
    for field in input_fields:
        _repro_digest(inputs[field], field.replace("_", " "))

    artifact_fields = {
        "build_fingerprint",
        "config_digest",
        "bundle_digest",
        "trace_index_digest",
        "canonical_replay_digest",
        "environment_digest",
        "lockfile_digest",
        "files",
    }
    artifacts = _closed_object(manifest["artifacts"], artifact_fields, "artifacts")
    for field in artifact_fields - {"files"}:
        _repro_digest(artifacts[field], field.replace("_", " "))
    files = artifacts["files"]
    if not isinstance(files, list) or not files or len(files) > 4096:
        raise BundleError("file inventory must be a bounded non-empty array")
    paths: set[str] = set()
    portable_paths: set[str] = set()
    ordered_paths: list[str] = []
    for index, item in enumerate(files):
        entry = _closed_object(
            item,
            {"path", "size", "media_type", "canonicalization", "digest"},
            f"file inventory entry {index}",
        )
        path = _repro_relative_path(entry["path"])
        portable_path = _portable_path_key(path)
        if portable_path == _portable_path_key("reproducibility-manifest.json"):
            raise BundleError("file inventory cannot own the reproducibility manifest")
        if path in paths:
            raise BundleError("file inventory contains a duplicate relative path")
        if portable_path in portable_paths:
            raise BundleError("file inventory contains a non-portable path collision")
        paths.add(path)
        portable_paths.add(portable_path)
        ordered_paths.append(path)
        if type(entry["size"]) is not int or not 0 <= entry["size"] <= 64 * 2**20:
            raise BundleError("file inventory size is invalid")
        media_type = entry["media_type"]
        _repro_nonempty(media_type, "file media type", maximum=128)
        if _MEDIA_TYPE.fullmatch(media_type) is None:
            raise BundleError("file media type is invalid")
        expected_media_type = _REQUIRED_MEDIA_TYPES.get(path)
        if expected_media_type is None and path.lower().endswith(".json"):
            expected_media_type = "application/json"
        if expected_media_type is not None and media_type != expected_media_type:
            raise BundleError(f"file media type does not match artifact: {path}")
        if entry["canonicalization"] != "exact-bytes":
            raise BundleError("file canonicalization must be exact-bytes")
        _repro_digest(entry["digest"], "file digest")
    if ordered_paths != sorted(ordered_paths):
        raise BundleError("file inventory must be sorted by path")
    if any(
        _portable_path_key(parent.as_posix()) in portable_paths
        for path in paths
        for parent in Path(path).parents
        if parent != Path(".")
    ):
        raise BundleError("file inventory contains a file-directory collision")

    run_fields = {
        "candidate_git_sha",
        "dirty",
        "platform",
        "runtime",
        "dependencies",
        "locale",
        "timezone",
        "environment",
        "seed_records",
        "retries",
        "aborts",
    }
    run = _closed_object(manifest["run"], run_fields, "run")
    if (
        not isinstance(run["candidate_git_sha"], str)
        or _REPRO_COMMIT.fullmatch(run["candidate_git_sha"]) is None
    ):
        raise BundleError("candidate Git SHA is invalid")
    if run["dirty"] is not False:
        raise BundleError("candidate checkout must be declared clean")
    for field in ("platform", "runtime"):
        _repro_nonempty(run[field], field, maximum=128)
    if run["locale"] != "C" or run["timezone"] != "UTC":
        raise BundleError("locale and timezone must be C and UTC")
    dependencies = run["dependencies"]
    if (
        not isinstance(dependencies, list)
        or len(dependencies) > 4096
        or any(
            not isinstance(item, str) or not item or len(item) > 512
            for item in dependencies
        )
        or len(dependencies) != len(set(dependencies))
        or dependencies != sorted(dependencies)
    ):
        raise BundleError("dependency inventory is invalid")
    seeds = run["seed_records"]
    if (
        not isinstance(seeds, list)
        or not seeds
        or len(seeds) > 4096
        or any(type(seed) is not int for seed in seeds)
        or len(seeds) != len(set(seeds))
    ):
        raise BundleError("seed record inventory is invalid")
    for field in ("retries", "aborts"):
        if type(run[field]) is not int or run[field] < 0:
            raise BundleError(f"{field} must be a non-negative integer")
    environment = run["environment"]
    if not isinstance(environment, dict) or len(environment) > 128:
        raise BundleError("environment allowlist is invalid")
    for name, value in environment.items():
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name) is None
            or not isinstance(value, str)
            or len(value) > 1024
        ):
            raise BundleError("environment allowlist is invalid")
        if SECRET.search(value):
            raise BundleError("secret-like material detected in environment")
        if _credential_environment_name(name) or any(
            marker in name
            for marker in (
                "TOKEN",
                "SECRET",
                "PASSWORD",
                "PRIVATE",
                "KEY",
                "CREDENTIAL",
                "AUTHORIZATION",
            )
        ):
            raise BundleError("credential-like environment names are forbidden")
        if _forbidden_declared_environment_name(name):
            raise BundleError("execution-influencing environment names are forbidden")

    metrics = manifest["metrics"]
    if not isinstance(metrics, list) or not metrics or len(metrics) > 1024:
        raise BundleError("metrics must be a bounded non-empty array")
    metric_fields = {
        "family",
        "name",
        "version",
        "value",
        "unit",
        "numerator",
        "denominator",
        "sample_count",
        "interval",
        "exclusions",
        "outcomes",
    }
    metric_identities: set[tuple[str, str]] = set()
    ordered_metric_identities: list[tuple[str, str]] = []
    for index, item in enumerate(metrics):
        metric = _closed_object(item, metric_fields, f"metric {index}")
        for field, maximum in (
            ("family", 128),
            ("name", 128),
            ("version", 64),
            ("unit", 64),
        ):
            _repro_nonempty(metric[field], f"metric {field}", maximum=maximum)
        identity = (metric["family"], metric["name"])
        if identity in metric_identities:
            raise BundleError("metric inventory contains a duplicate identity")
        metric_identities.add(identity)
        ordered_metric_identities.append(identity)
        if not isinstance(metric["value"], (int, float)) or isinstance(
            metric["value"], bool
        ):
            raise BundleError("metric value is invalid")
        for field in ("numerator", "denominator"):
            value = metric[field]
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise BundleError(f"metric {field} is invalid")
        if (metric["numerator"] is None) != (metric["denominator"] is None):
            raise BundleError("metric numerator and denominator must be paired")
        if type(metric["sample_count"]) is not int or metric["sample_count"] < 0:
            raise BundleError("metric sample count is invalid")
        interval = _closed_object(
            metric["interval"],
            {"method", "confidence_level", "low", "high", "parameters"},
            "metric interval",
        )
        _repro_nonempty(interval["method"], "interval method", maximum=64)
        confidence = interval["confidence_level"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 < confidence < 1:
            raise BundleError("interval confidence level is invalid")
        if not all(
            isinstance(interval[field], (int, float))
            and not isinstance(interval[field], bool)
            for field in ("low", "high")
        ) or interval["low"] > interval["high"]:
            raise BundleError("metric interval bounds are invalid")
        if not interval["low"] <= metric["value"] <= interval["high"]:
            raise BundleError("metric value must fall within its interval")
        parameters = interval["parameters"]
        if (
            not isinstance(parameters, dict)
            or len(parameters) > 32
            or any(
                not isinstance(key, str)
                or not 1 <= len(key) <= 64
                or value is not None
                and not isinstance(value, (str, int, float, bool))
                for key, value in parameters.items()
            )
        ):
            raise BundleError("metric interval parameters are invalid")
        exclusions = metric["exclusions"]
        if (
            not isinstance(exclusions, list)
            or len(exclusions) > 1024
            or any(
                not isinstance(item, str) or not item or len(item) > 512
                for item in exclusions
            )
            or len(exclusions) != len(set(exclusions))
            or exclusions != sorted(exclusions)
        ):
            raise BundleError("metric exclusions are invalid")
        outcomes = _closed_object(
            metric["outcomes"],
            {"missing", "unsupported", "failed", "aborted", "not_measured"},
            "metric outcomes",
        )
        if any(type(value) is not int or value < 0 for value in outcomes.values()):
            raise BundleError("metric outcome counts are invalid")
    if ordered_metric_identities != sorted(ordered_metric_identities):
        raise BundleError("metric inventory must be sorted by family and name")

    disclosure_fields = {
        "software_license",
        "data_license",
        "source_revision",
        "redistribution_permitted",
        "pii_present",
        "consent_documented",
        "takedown_process",
        "custody_class",
        "operator_identity",
        "operator_role",
        "signer_role",
        "disclosure_state",
        "independent_reproduction",
    }
    disclosures = _closed_object(
        manifest["disclosures"], disclosure_fields, "disclosures"
    )
    for field, maximum in (
        ("software_license", 256),
        ("data_license", 256),
        ("source_revision", 256),
        ("takedown_process", 512),
        ("custody_class", 128),
        ("operator_identity", 256),
        ("operator_role", 128),
        ("signer_role", 128),
    ):
        _repro_nonempty(
            disclosures[field], field.replace("_", " "), maximum=maximum
        )
    for field in ("redistribution_permitted", "pii_present", "consent_documented"):
        if type(disclosures[field]) is not bool:
            raise BundleError(f"{field.replace('_', ' ')} disclosure is invalid")
    if disclosures["redistribution_permitted"] is not True:
        raise BundleError("redistribution rights are required")
    if (
        disclosures["pii_present"] is True
        and disclosures["consent_documented"] is not True
    ):
        raise BundleError("PII requires documented consent")
    if disclosures["disclosure_state"] != "COMPLETE":
        raise BundleError("disclosure state must be COMPLETE")
    independent = disclosures["independent_reproduction"]
    if independent is not None:
        independent = _closed_object(
            independent,
            {
                "receipt_digest",
                "reproducer_identity",
                "public_key_digest",
                "signed",
            },
            "independent reproduction",
        )
        _repro_digest(independent["receipt_digest"], "reproduction receipt")
        _repro_digest(independent["public_key_digest"], "reproducer public key")
        _repro_nonempty(
            independent["reproducer_identity"],
            "reproducer identity",
            maximum=256,
        )
        if independent["signed"] is not True:
            raise BundleError("independent reproduction receipt must be signed")

    reproduction = _closed_object(
        manifest["reproduction"], {"argv", "network"}, "reproduction"
    )
    if reproduction["argv"] != list(REPRODUCTION_ARGV):
        raise BundleError("reproduction command does not match the frozen argv")
    if reproduction["network"] != "forbidden":
        raise BundleError("reproduction network must be forbidden")
    return {
        "schema_version": REPRODUCIBILITY_SCHEMA_VERSION,
        "track_kind": track_kind,
        "valid": True,
    }


def _sha256_reference(path: Path) -> str:
    return _inspect_artifact(path)[1]


def _files_equal(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while True:
            left_chunk = left_handle.read(1024 * 1024)
            right_chunk = right_handle.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def _inspect_artifact(path: Path) -> tuple[int, str, bool]:
    try:
        path_stat = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or path_stat.st_mode & _UNSAFE_MODE_BITS
        ):
            raise BundleError("artifact changed before inspection")
        digest = hashlib.sha256()
        size = 0
        secret_found = False
        carry = b""
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or (opened_stat.st_dev, opened_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise BundleError("artifact changed before inspection")
            while chunk := handle.read(_SECRET_SCAN_CHUNK_SIZE):
                size += len(chunk)
                digest.update(chunk)
                window = carry + chunk
                if SECRET_BYTES.search(window):
                    secret_found = True
                carry = window[-_SECRET_SCAN_OVERLAP:]
            current_stat = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or current_stat.st_nlink != 1
                or (current_stat.st_dev, current_stat.st_ino)
                != (opened_stat.st_dev, opened_stat.st_ino)
            ):
                raise BundleError("artifact changed during inspection")
    except BundleError:
        raise
    except OSError as exc:
        raise BundleError("artifact changed during inspection") from exc
    return size, "sha256:" + digest.hexdigest(), secret_found


def _read_bound_artifact(path: Path, entry: dict[str, Any]) -> bytes:
    """Read the exact regular inode described by one inventory entry."""
    try:
        path_stat = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or path_stat.st_mode & _UNSAFE_MODE_BITS
        ):
            raise BundleError("artifact changed before bound read")
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or (opened_stat.st_dev, opened_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise BundleError("artifact changed before bound read")
            raw = handle.read(entry["size"] + 1)
            current_stat = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or current_stat.st_nlink != 1
                or (current_stat.st_dev, current_stat.st_ino)
                != (opened_stat.st_dev, opened_stat.st_ino)
            ):
                raise BundleError("artifact changed during bound read")
    except BundleError:
        raise
    except OSError as exc:
        raise BundleError("artifact changed during bound read") from exc
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if len(raw) != entry["size"] or digest != entry["digest"]:
        raise BundleError(f"digest mismatch: {entry['path']}")
    return raw


def _load_bound_json(path: Path, entry: dict[str, Any]) -> object:
    raw = _read_bound_artifact(path, entry)
    try:
        return _parse_json(raw.decode("utf-8"), entry["path"])
    except UnicodeDecodeError as exc:
        raise BundleError(f"artifact is not UTF-8: {entry['path']}") from exc


def _copy_inventory_artifact(
    source: Path, target: Path, entry: dict[str, Any]
) -> None:
    """Copy one validated source inode without reopening its pathname."""
    try:
        path_stat = source.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or path_stat.st_mode & _UNSAFE_MODE_BITS
        ):
            raise BundleError("reproducibility artifact changed before copy")
        with source.open("rb") as source_handle:
            opened_stat = os.fstat(source_handle.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or (opened_stat.st_dev, opened_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise BundleError("reproducibility artifact changed before copy")
            digest = hashlib.sha256()
            size = 0
            secret_found = False
            carry = b""
            with target.open("xb") as target_handle:
                while chunk := source_handle.read(_SECRET_SCAN_CHUNK_SIZE):
                    target_handle.write(chunk)
                    size += len(chunk)
                    digest.update(chunk)
                    window = carry + chunk
                    if SECRET_BYTES.search(window):
                        secret_found = True
                    carry = window[-_SECRET_SCAN_OVERLAP:]
            current_stat = source.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or current_stat.st_nlink != 1
                or (current_stat.st_dev, current_stat.st_ino)
                != (opened_stat.st_dev, opened_stat.st_ino)
            ):
                raise BundleError("reproducibility artifact changed during copy")
    except BundleError:
        raise
    except OSError as exc:
        raise BundleError("reproducibility artifact changed during copy") from exc
    if (
        size != entry["size"]
        or "sha256:" + digest.hexdigest() != entry["digest"]
    ):
        raise BundleError(f"digest mismatch: {entry['path']}")
    if secret_found:
        raise BundleError("secret-like material detected")
    os.chmod(target, stat.S_IMODE(opened_stat.st_mode))


def _reject_decoded_secrets(value: object) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str) and SECRET.search(current):
            raise BundleError("secret-like material detected in decoded artifact")
        if isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _validate_artifact_media(
    path: Path, media_type: str, entry: dict[str, Any] | None = None
) -> None:
    raw = _read_bound_artifact(path, entry) if entry is not None else None
    if media_type == "application/json":
        try:
            value = (
                _parse_json(raw.decode("utf-8"), path.name)
                if raw is not None
                else _load_json(path)
            )
        except (OSError, UnicodeError, BundleError) as exc:
            raise BundleError("artifact declared as JSON is invalid") from exc
        _reject_decoded_secrets(value)
        return
    if media_type == "application/x-ndjson":
        try:
            if raw is not None:
                records = raw.splitlines(keepends=True)
            else:
                records = path.open("rb")
            with (nullcontext(records) if raw is not None else records) as lines:
                for line_number, raw_line in enumerate(lines, 1):
                    try:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            raise BundleError("NDJSON contains an empty record")
                        value = _parse_json(line, f"NDJSON record {line_number}")
                    except (UnicodeError, BundleError) as exc:
                        raise BundleError("artifact declared as NDJSON is invalid") from exc
                    _reject_decoded_secrets(value)
        except OSError as exc:
            raise BundleError("artifact declared as NDJSON is invalid") from exc
        return
    if media_type.startswith("text/"):
        try:
            if raw is not None:
                raw.decode("utf-8")
            else:
                decoder = codecs.getincrementaldecoder("utf-8")()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        decoder.decode(chunk)
                decoder.decode(b"", final=True)
        except (OSError, UnicodeError) as exc:
            raise BundleError("artifact declared as text is not UTF-8") from exc


def _runtime_platform() -> str:
    return f"{sys.platform}-{platform.machine().lower()}"


def _runtime_version() -> str:
    return f"cpython-{sys.version_info.major}.{sys.version_info.minor}"


def _locked_dependencies(path: Path) -> list[str]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise BundleError("lockfile dependency inventory cannot be read") from exc
    packages = payload.get("package") if isinstance(payload, dict) else None
    if not isinstance(packages, list) or not packages:
        raise BundleError("lockfile dependency inventory is invalid")
    dependencies: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            raise BundleError("lockfile dependency inventory is invalid")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not name:
            raise BundleError("lockfile dependency inventory is invalid")
        if isinstance(version, str) and version:
            dependencies.append(f"{name}=={version}")
            continue
        source = package.get("source")
        if not isinstance(source, dict) or len(source) != 1:
            raise BundleError("lockfile dependency inventory is invalid")
        source_kind, source_value = next(iter(source.items()))
        if (
            not isinstance(source_kind, str)
            or not source_kind
            or not isinstance(source_value, str)
            or not source_value
        ):
            raise BundleError("lockfile dependency inventory is invalid")
        dependencies.append(f"{name} @ {source_kind}:{source_value}")
    ordered = sorted(dependencies)
    if len(ordered) != len(set(ordered)):
        raise BundleError("lockfile dependency inventory contains duplicates")
    return ordered


def _verify_embedded_legacy_bundle(root: Path) -> dict[str, Any]:
    manifest = _load_json(root / "bundle-manifest.json")
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        raise BundleError("embedded public bundle manifest is invalid")
    with tempfile.TemporaryDirectory() as temporary:
        legacy = Path(temporary) / "bundle"
        legacy.mkdir()
        for name in (*files.keys(), "bundle-manifest.json"):
            if not isinstance(name, str) or _repro_relative_path(name) != name:
                raise BundleError("embedded public bundle inventory is invalid")
            source = root / name
            if source.is_symlink() or not source.is_file():
                raise BundleError("embedded public bundle file is invalid")
            shutil.copyfile(source, legacy / name)
        return verify_bundle(legacy)


def _reproducibility_tree(
    root: Path, expected_files: set[str], expected_directories: set[str]
) -> tuple[set[str], set[str]]:
    """Return real files/directories below root without following links."""
    root_resolved = root.resolve()
    files: set[str] = set()
    directories: set[str] = set()
    pending = [root]
    seen = 0
    maximum_nodes = len(expected_files) + len(expected_directories)
    while pending:
        parent = pending.pop()
        try:
            for child in parent.iterdir():
                seen += 1
                if seen > maximum_nodes:
                    raise BundleError("reproducibility bundle inventory mismatch")
                relative = child.relative_to(root).as_posix()
                is_junction = getattr(child, "is_junction", lambda: False)()
                if child.is_symlink() or is_junction:
                    raise BundleError("links and junctions are forbidden")
                try:
                    path_stat = child.stat(follow_symlinks=False)
                except OSError as exc:
                    raise BundleError(
                        "reproducibility bundle path cannot be inspected"
                    ) from exc
                if path_stat.st_mode & _UNSAFE_MODE_BITS:
                    raise BundleError("special permission bits are forbidden")
                try:
                    resolved = child.resolve(strict=True)
                except OSError as exc:
                    raise BundleError(
                        "reproducibility bundle path cannot be resolved"
                    ) from exc
                if root_resolved not in resolved.parents:
                    raise BundleError("reproducibility bundle path escapes root")
                if child.is_dir():
                    if relative not in expected_directories:
                        raise BundleError("reproducibility bundle inventory mismatch")
                    directories.add(relative)
                    pending.append(child)
                elif child.is_file():
                    if relative not in expected_files:
                        raise BundleError("reproducibility bundle inventory mismatch")
                    if path_stat.st_nlink != 1:
                        raise BundleError("hard-linked files are forbidden")
                    files.add(relative)
                else:
                    raise BundleError("non-files are forbidden")
        except BundleError:
            raise
        except OSError as exc:
            raise BundleError("reproducibility bundle tree cannot be read") from exc
    return files, directories


def _reject_reproducibility_link_path(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise BundleError("reproducibility paths must not contain links or junctions")


def _publish_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing any destination entry."""
    if os.name == "nt":
        source.rename(destination)
        return

    import ctypes

    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        try:
            rename = library.renameat2
        except AttributeError as exc:
            raise BundleError("atomic no-replace publication is unavailable") from exc
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            _AT_FDCWD,
            source_bytes,
            _AT_FDCWD,
            destination_bytes,
            _RENAME_NOREPLACE,
        )
    elif sys.platform == "darwin":
        try:
            rename = library.renamex_np
        except AttributeError as exc:
            raise BundleError("atomic no-replace publication is unavailable") from exc
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(source_bytes, destination_bytes, _RENAME_EXCL)
    else:
        raise BundleError("atomic no-replace publication is unavailable")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(
            error_number,
            "refusing to overwrite reproducibility bundle",
            destination,
        )
    raise OSError(error_number, os.strerror(error_number), destination)


def _load_reproducibility_manifest(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one bounded, canonical, validated manifest snapshot."""
    manifest_path = root / "reproducibility-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BundleError("reproducibility manifest must be a real file")
    try:
        manifest_raw = manifest_path.read_bytes()
    except OSError as exc:
        raise BundleError("reproducibility manifest cannot be read") from exc
    if len(manifest_raw) > 4 * 2**20:
        raise BundleError("reproducibility manifest exceeds size bound")
    try:
        manifest = _parse_json(
            manifest_raw.decode("utf-8"), "reproducibility-manifest.json"
        )
    except UnicodeDecodeError as exc:
        raise BundleError("reproducibility manifest is not UTF-8") from exc
    if manifest_raw != _canonical(manifest):
        raise BundleError("reproducibility manifest bytes must be canonical")
    validated = validate_reproducibility_manifest(manifest)
    return manifest, validated


def verify_reproducibility_bundle(bundle: Path | str) -> dict[str, Any]:
    """Verify a REPRO-001 bundle without executing bundle-controlled content."""
    root = Path(bundle)
    _reject_reproducibility_link_path(root)
    if (
        not root.is_dir()
        or root.is_symlink()
        or getattr(root, "is_junction", lambda: False)()
    ):
        raise BundleError("reproducibility bundle must be a real directory")
    manifest_path = root / "reproducibility-manifest.json"
    manifest, validated = _load_reproducibility_manifest(root)
    artifacts = manifest["artifacts"]
    inventory = artifacts["files"]
    names = {entry["path"] for entry in inventory}
    entries = {entry["path"]: entry for entry in inventory}
    expected_directories = {
        parent.as_posix()
        for name in names
        for parent in Path(name).parents
        if parent != Path(".")
    }
    expected_files = names | {manifest_path.name}
    actual_files, actual_directories = _reproducibility_tree(
        root, expected_files, expected_directories
    )
    if (
        actual_files != expected_files
        or actual_directories != expected_directories
    ):
        raise BundleError("reproducibility bundle inventory mismatch")
    for entry in inventory:
        path = root / entry["path"]
        try:
            if path.stat().st_size != entry["size"]:
                raise BundleError(f"digest mismatch: {entry['path']}")
            size, digest, secret_found = _inspect_artifact(path)
        except OSError as exc:
            raise BundleError("reproducibility bundle file cannot be read") from exc
        if size != entry["size"] or digest != entry["digest"]:
            raise BundleError(f"digest mismatch: {entry['path']}")
        if secret_found:
            raise BundleError("secret-like material detected")
        _validate_artifact_media(path, entry["media_type"], entry)

    bindings = {
        "build_fingerprint": "build.json",
        "config_digest": "config.json",
        "bundle_digest": "bundle-manifest.json",
        "trace_index_digest": "traces.jsonl",
        "environment_digest": "environment.json",
        "lockfile_digest": "uv.lock",
    }
    for field, name in bindings.items():
        if name not in names or artifacts[field] != _sha256_reference(root / name):
            raise BundleError(f"digest mismatch: {field}")
    if manifest["run"]["dependencies"] != _locked_dependencies(root / "uv.lock"):
        raise BundleError("dependency inventory does not match lockfile")

    input_bindings = {
        "benchmark_manifest_digest": "benchmark.json",
        "dataset_manifest_digest": "benchmark.json",
        "fixture_manifest_digest": "fixture-manifest.json",
        "generator_manifest_digest": "generator-manifest.json",
        "adapter_manifest_digest": "adapter-manifest.json",
        "scorer_manifest_digest": "scorer-manifest.json",
        "baseline_manifest_digest": "baseline-manifest.json",
        "judge_manifest_digest": "judge.json",
        "prompt_manifest_digest": "prompt-manifest.json",
    }
    inputs = manifest["inputs"]
    for field, name in input_bindings.items():
        if name not in names or inputs[field] != _sha256_reference(root / name):
            raise BundleError(f"digest mismatch: {field}")
    environment_raw = _read_bound_artifact(
        root / "environment.json", entries["environment.json"]
    )
    environment_record = _load_bound_json(
        root / "environment.json", entries["environment.json"]
    )
    expected_environment = {
        field: manifest["run"][field]
        for field in (
            "platform",
            "runtime",
            "dependencies",
            "locale",
            "timezone",
            "environment",
        )
    }
    if environment_record != expected_environment:
        raise BundleError("environment manifest does not match run declaration")
    if environment_raw != _canonical(environment_record):
        raise BundleError("environment manifest bytes must be canonical")
    _verify_embedded_legacy_bundle(root)

    required = {
        "result.json",
        "ledger.jsonl",
        "ledger.jsonl.head.json",
        "ledger.jsonl.lock",
        "ledger-public.pem",
        "canonical-replay.json",
    }
    independent = manifest["disclosures"]["independent_reproduction"]
    if independent is not None:
        required.update(
            {
                "independent-ledger.jsonl",
                "independent-ledger.jsonl.head.json",
                "independent-ledger.jsonl.lock",
                "independent-public.pem",
            }
        )
    missing = sorted(required - names)
    if missing:
        raise BundleError(f"reproducibility bundle missing required file: {missing[0]}")
    result_raw = _read_bound_artifact(root / "result.json", entries["result.json"])
    result = _load_bound_json(root / "result.json", entries["result.json"])
    from leaderboard.validate import validate_record, verify_result_digests

    result_errors = validate_record(result)
    if result_errors:
        raise BundleError("result-v2 validation failed: " + ", ".join(result_errors))
    result_ref = manifest["result_ref"]
    if (
        result.get("schema_version") != "mnemosyne.leaderboard.result/v2"
        or result.get("record_id") != result_ref["record_id"]
        or result.get("run_commit") != manifest["run"]["candidate_git_sha"]
        or result.get("track_kind") != result_ref["track_kind"]
        or result.get("lineage") != result_ref["lineage"]
        or "sha256:" + hashlib.sha256(result_raw).hexdigest()
        != result_ref["result_digest"]
    ):
        raise BundleError("result-v2 reference mismatch")
    if manifest["disclosures"]["source_revision"] != result.get("run_commit"):
        raise BundleError("source revision does not match result-v2 run commit")
    benchmark_manifest = _load_bound_json(
        root / "benchmark.json", entries["benchmark.json"]
    )
    _verify_result_bundle_bindings(result, manifest, benchmark_manifest)
    digest_errors = verify_result_digests(
        result,
        {
            name: _read_bound_artifact(root / name, entries[name])
            for name in (
                "build.json",
                "config.json",
                "bundle-manifest.json",
                "traces.jsonl",
            )
        },
    )
    if digest_errors:
        raise BundleError("result-v2 artifact digest mismatch: " + ", ".join(digest_errors))

    result_metrics = result.get("metrics")
    declared_metrics = manifest["metrics"]
    if not isinstance(result_metrics, list) or len(result_metrics) != len(declared_metrics):
        raise BundleError("result-v2 metric inventory mismatch")
    for declared in declared_metrics:
        candidates = [
            metric
            for metric in result_metrics
            if isinstance(metric, dict)
            and metric.get("name") == declared["name"]
            and metric.get("family") == declared["family"]
        ]
        if len(candidates) != 1:
            raise BundleError("result-v2 metric inventory mismatch")
        metric = candidates[0]
        interval = metric.get("confidence_interval")
        declared_interval = declared["interval"]
        if (
            metric.get("value") != declared["value"]
            or metric.get("unit") != declared["unit"]
            or not isinstance(interval, dict)
            or interval.get("low") != declared_interval["low"]
            or interval.get("high") != declared_interval["high"]
        ):
            raise BundleError("result-v2 metric binding mismatch")

    _verify_recomputed_metric_declarations(
        _load_bound_json(root / "metrics.json", entries["metrics.json"]),
        declared_metrics,
    )

    from leaderboard.ledger import LedgerError, verify_ledger
    from mnemosyne.evidence_signing import (
        EvidenceSignatureError,
        _public_key_sha256,
        load_public_key,
    )

    try:
        ledger_entries = verify_ledger(
            root / "ledger.jsonl", root / "ledger-public.pem"
        )
    except LedgerError as exc:
        raise BundleError("signed-ledger verification failed") from exc
    matching_entries = [
        entry
        for entry in ledger_entries
        if entry.get("entry_digest") == result_ref["ledger_entry_digest"]
    ]
    if (
        len(matching_entries) != 1
        or matching_entries[0].get("status") != "succeeded"
        or matching_entries[0].get("result") != result
    ):
        raise BundleError("signed-ledger inclusion reference mismatch")
    if independent is not None:
        independent_key = root / "independent-public.pem"
        try:
            operator_key_fingerprint = _public_key_sha256(
                load_public_key(root / "ledger-public.pem")
            )
            independent_key_fingerprint = _public_key_sha256(
                load_public_key(independent_key)
            )
        except EvidenceSignatureError as exc:
            raise BundleError("independent reproduction public key is invalid") from exc
        if (
            _sha256_reference(independent_key) != independent["public_key_digest"]
            or independent_key_fingerprint == operator_key_fingerprint
        ):
            raise BundleError("independent reproduction key is not distinct and bound")
        try:
            independent_entries = verify_ledger(
                root / "independent-ledger.jsonl", independent_key
            )
        except LedgerError as exc:
            raise BundleError("independent signed-ledger verification failed") from exc
        receipt_entries = [
            entry
            for entry in independent_entries
            if entry.get("entry_digest") == independent["receipt_digest"]
        ]
        if (
            len(receipt_entries) != 1
            or receipt_entries[0].get("status") != "succeeded"
            or receipt_entries[0].get("result") != result
            or receipt_entries[0].get("entrant_id")
            != independent["reproducer_identity"]
            or receipt_entries[0].get("entrant_id")
            == matching_entries[0].get("entrant_id")
        ):
            raise BundleError("independent reproduction receipt is not independently bound")
    replay = _load_bound_json(
        root / "canonical-replay.json", entries["canonical-replay.json"]
    )
    if (
        not isinstance(replay, dict)
        or replay.get("seed_records") != manifest["run"]["seed_records"]
    ):
        raise BundleError("canonical replay seed records do not match run custody")
    replay_manifests = replay.get("manifests")
    expected_replay_manifests = {
        "bundle_manifest_sha256": artifacts["bundle_digest"].removeprefix("sha256:"),
        "fixture_manifest_sha256": inputs["fixture_manifest_digest"].removeprefix(
            "sha256:"
        ),
        "generator_manifest_sha256": inputs["generator_manifest_digest"].removeprefix(
            "sha256:"
        ),
    }
    if replay_manifests != expected_replay_manifests:
        raise BundleError("canonical replay manifest custody does not match artifacts")
    replay_build = replay.get("build")
    retained_build = _load_bound_json(root / "build.json", entries["build.json"])
    if (
        not isinstance(replay_build, dict)
        or not isinstance(retained_build, dict)
        or replay_build.get("candidate_git_sha") != manifest["run"]["candidate_git_sha"]
        or replay_build.get("system_seam") != retained_build.get("system_seam")
    ):
        raise BundleError("canonical replay build custody does not match run")
    replay_digest = "sha256:" + canonical_replay_digest(replay)
    if replay_digest != artifacts["canonical_replay_digest"]:
        raise BundleError("canonical replay digest mismatch")
    final_files, final_directories = _reproducibility_tree(
        root, expected_files, expected_directories
    )
    if final_files != expected_files or final_directories != expected_directories:
        raise BundleError("reproducibility bundle changed during verification")
    for entry in inventory:
        path = root / entry["path"]
        try:
            size, digest, secret_found = _inspect_artifact(path)
        except OSError as exc:
            raise BundleError("reproducibility bundle changed during verification") from exc
        if size != entry["size"] or digest != entry["digest"]:
            raise BundleError(f"artifact changed during verification: {entry['path']}")
        if secret_found:
            raise BundleError("secret-like material detected")
    try:
        if manifest_path.read_bytes() != _canonical(manifest):
            raise BundleError("reproducibility manifest changed during verification")
    except OSError as exc:
        raise BundleError("reproducibility manifest changed during verification") from exc
    return validated


def assemble_reproducibility_bundle(
    source: Path | str,
    destination: Path | str,
    manifest: object,
) -> dict[str, Any]:
    """Atomically package and verify manifest-owned REPRO-001 artifacts."""
    validate_reproducibility_manifest(manifest)
    if not isinstance(manifest, dict):  # narrowed by the validator
        raise BundleError("manifest must be an object")
    source_path = Path(source)
    destination_path = Path(destination)
    _reject_reproducibility_link_path(source_path)
    _reject_reproducibility_link_path(destination_path)
    source_root = source_path.resolve()
    destination_root = destination_path.resolve()
    if not source_root.is_dir():
        raise BundleError("reproducibility artifact source must be a real directory")
    if os.path.lexists(destination_root):
        raise FileExistsError(f"refusing to overwrite bundle: {destination_root}")
    if source_root == destination_root or source_root in destination_root.parents:
        raise BundleError("assembly destination must be outside the artifact source")

    inventory = manifest["artifacts"]["files"]
    names = {entry["path"] for entry in inventory}
    expected_directories = {
        parent.as_posix()
        for name in names
        for parent in Path(name).parents
        if parent != Path(".")
    }
    actual_files, actual_directories = _reproducibility_tree(
        source_root, names, expected_directories
    )
    if actual_files != names or actual_directories != expected_directories:
        raise BundleError("reproducibility artifact source inventory mismatch")

    destination_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_root.name}-assemble-", dir=destination_root.parent
        )
    )
    final = staging / "final"
    try:
        final.mkdir()
        for entry in inventory:
            name = entry["path"]
            source_file = source_root / name
            target = final / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_inventory_artifact(source_file, target, entry)
        (final / "reproducibility-manifest.json").write_bytes(_canonical(manifest))
        result = verify_reproducibility_bundle(final)
        if os.path.lexists(destination_root):
            raise FileExistsError(
                f"refusing to overwrite bundle: {destination_root}"
            )
        _publish_directory_noreplace(final, destination_root)
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _verify_result_bundle_bindings(
    result: dict[str, Any], manifest: dict[str, Any], benchmark_manifest: object
) -> None:
    if not isinstance(benchmark_manifest, dict) or not isinstance(
        benchmark_manifest.get("metadata"), dict
    ):
        raise BundleError("benchmark manifest metadata is invalid")
    metadata = benchmark_manifest["metadata"]
    identity = result.get("identity")
    run_profile = result.get("run_profile")
    publication = result.get("publication")
    operator_entry = result.get("operator_entry")
    if not all(
        isinstance(value, dict)
        for value in (identity, run_profile, publication, operator_entry)
    ):
        raise BundleError("result-v2 run custody is incomplete")
    run = manifest["run"]
    disclosures = manifest["disclosures"]
    inputs = manifest["inputs"]
    excluded_count = metadata.get("excluded_count", 0)
    if (
        type(excluded_count) is not int
        or excluded_count < 0
        or any(
            len(metric["exclusions"]) != excluded_count
            or metric["outcomes"]["aborted"] != run["aborts"]
            for metric in manifest["metrics"]
        )
    ):
        raise BundleError("bundle outcome accounting does not match run custody")
    if (
        result.get("benchmark") != metadata.get("suite")
        or result.get("benchmark_version") != metadata.get("revision")
        or identity.get("benchmark_id") != metadata.get("suite")
        or identity.get("benchmark_version") != metadata.get("revision")
        or identity.get("adapter_id") != metadata.get("adapter")
        or identity.get("dataset_split_digest")
        != inputs["dataset_manifest_digest"]
        or identity.get("seed") not in run["seed_records"]
        or run_profile.get("seeds") != run["seed_records"]
        or run_profile.get("retries") != run["retries"]
        or run_profile.get("aborts") != run["aborts"]
        or publication.get("publishable") != metadata.get("publishable")
        or publication.get("pbpp_headline_eligible")
        != metadata.get("pbpp_headline_eligible")
        or operator_entry.get("operator") != disclosures["operator_identity"]
        or result.get("custody") != disclosures["custody_class"]
        or result.get("signer_role") != disclosures["signer_role"]
    ):
        raise BundleError("result-v2 does not bind embedded bundle custody")
    for result_field, metadata_field in (
        ("module_id", "module_id"),
        ("admission_state", "admission_state"),
        ("track_kind", "track_kind"),
    ):
        if metadata_field in metadata and result.get(result_field) != metadata.get(
            metadata_field
        ):
            raise BundleError("result-v2 does not bind embedded bundle custody")


def _verify_recomputed_metric_declarations(
    recomputed: object, declared_metrics: list[dict[str, Any]]
) -> None:
    if not isinstance(recomputed, dict):
        raise BundleError("metrics do not recompute from raw traces")
    trace_count = recomputed.get("trace_count")
    if type(trace_count) is not int or trace_count < 0:
        raise BundleError("metrics do not recompute from raw traces")
    if "metric" in recomputed:
        metric_name = recomputed.get("metric")
        measured = {metric_name: recomputed.get("value")}
        intervals = {metric_name: recomputed.get("interval")}
        numerators = {metric_name: recomputed.get("successes")}
        denominators = {metric_name: recomputed.get("total")}
        version = "1"
    else:
        measured = recomputed.get("metrics")
        intervals = recomputed.get("intervals")
        numerators = {}
        denominators = {}
        version = str(recomputed.get("profile_version"))
    if (
        not isinstance(measured, dict)
        or not isinstance(intervals, dict)
        or any(not isinstance(name, str) for name in measured)
        or set(measured) != set(intervals)
        or set(measured) != {metric["name"] for metric in declared_metrics}
    ):
        raise BundleError("metrics do not recompute from raw traces")
    for declared in declared_metrics:
        name = declared["name"]
        interval = intervals[name]
        if not isinstance(interval, dict):
            raise BundleError("metrics do not recompute from raw traces")
        parameters = {
            key: value
            for key, value in interval.items()
            if key not in {"confidence", "high", "low", "method"}
        }
        numerator = declared["numerator"]
        denominator = declared["denominator"]
        if name not in numerators:
            expected_numerator = measured[name] * trace_count
        else:
            expected_numerator = numerators.get(name)
        if name not in denominators:
            expected_denominator = trace_count
        else:
            expected_denominator = denominators.get(name)
        if (
            declared["version"] != version
            or measured[name] != declared["value"]
            or trace_count != declared["sample_count"]
            or (numerator is not None and numerator != expected_numerator)
            or (denominator is not None and denominator != expected_denominator)
            or interval.get("method") != declared["interval"]["method"]
            or interval.get("confidence")
            != declared["interval"]["confidence_level"]
            or interval.get("low") != declared["interval"]["low"]
            or interval.get("high") != declared["interval"]["high"]
            or parameters != declared["interval"]["parameters"]
        ):
            raise BundleError("metrics do not recompute from raw traces")


def _require_clean_reproduction_checkout(expected_sha: str) -> None:
    """Require the command to run at the manifest-bound clean Git checkout."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT", "WINDIR"}
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_WORK_TREE": str(Path.cwd().resolve()),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
    )
    git = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
    ]
    try:
        head = subprocess.run(
            [*git, "rev-parse", "HEAD"],
            cwd=Path.cwd(),
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        top_level = subprocess.run(
            [*git, "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            [*git, "status", "--porcelain"],
            cwd=Path.cwd(),
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        symbolic = subprocess.run(
            [*git, "symbolic-ref", "-q", "HEAD"],
            cwd=Path.cwd(),
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleError("reproduction checkout could not be verified") from exc
    if head != expected_sha:
        raise BundleError("reproduction checkout does not match candidate Git SHA")
    if Path(top_level).resolve() != Path.cwd().resolve():
        raise BundleError("reproduction command must run from repository root")
    if symbolic.returncode == 0:
        raise BundleError("reproduction checkout must be detached")
    if symbolic.returncode != 1:
        raise BundleError("reproduction checkout state could not be verified")
    if dirty:
        raise BundleError("reproduction checkout is dirty")


def reproduce_reproducibility_bundle(
    source: Path | str, destination: Path | str
) -> dict[str, Any]:
    """Recompute metrics from retained traces and atomically reproduce the bundle."""
    source_path = Path(source)
    destination_path = Path(destination)
    _reject_reproducibility_link_path(source_path)
    _reject_reproducibility_link_path(destination_path)
    source_root = source_path.resolve()
    destination_root = destination_path.resolve()
    if destination_root.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination_root}")
    if source_root == destination_root or source_root in destination_root.parents:
        raise BundleError("reproduction destination must be outside the source bundle")
    manifest, _ = _load_reproducibility_manifest(source_root)
    verify_reproducibility_bundle(source_root)
    try:
        if (source_root / "reproducibility-manifest.json").read_bytes() != _canonical(
            manifest
        ):
            raise BundleError("reproducibility manifest changed during reproduction")
    except OSError as exc:
        raise BundleError("reproducibility manifest changed during reproduction") from exc
    expected_sha = manifest["run"]["candidate_git_sha"]
    _require_clean_reproduction_checkout(expected_sha)
    if manifest["run"]["platform"] != _runtime_platform():
        raise BundleError("reproduction platform does not match manifest")
    if manifest["run"]["runtime"] != _runtime_version():
        raise BundleError("reproduction runtime does not match manifest")
    checkout_lock = Path.cwd() / "uv.lock"
    if (
        not checkout_lock.is_file()
        or checkout_lock.is_symlink()
        or _sha256_reference(checkout_lock)
        != manifest["artifacts"]["lockfile_digest"]
    ):
        raise BundleError("reproduction checkout lockfile digest mismatch")
    inherited_credentials = sorted(
        name
        for name in os.environ
        if _credential_environment_name(name)
    )
    if inherited_credentials:
        raise BundleError("reproduction environment contains inherited credentials")
    declared_environment = manifest["run"]["environment"]
    influential_environment = sorted(
        name
        for name in os.environ
        if _undeclared_influential_environment_name(
            name, set(declared_environment)
        )
    )
    if influential_environment:
        raise BundleError("reproduction environment contains undeclared influences")
    if os.environ.get("UV_OFFLINE", "").lower() not in {"1", "true"}:
        raise BundleError("reproduction requires UV_OFFLINE=1")
    if os.environ.get("UV_RUN_RECURSION_DEPTH") != "1":
        raise BundleError("reproduction requires one isolated uv run layer")
    if any(
        os.environ.get(name) != value
        for name, value in declared_environment.items()
    ):
        raise BundleError("reproduction environment does not match manifest allowlist")
    if (
        os.environ.get("LC_ALL") != manifest["run"]["locale"]
        or os.environ.get("TZ") != manifest["run"]["timezone"]
    ):
        raise BundleError("reproduction locale or timezone does not match manifest")
    destination_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_root.name}-reproduce-", dir=destination_root.parent
        )
    )
    final = staging / "final"
    try:
        benchmark = _load_json(source_root / "benchmark.json")
        config = _load_json(source_root / "config.json")
        if not isinstance(benchmark, dict) or not isinstance(config, dict):
            raise BundleError("embedded benchmark or config is invalid")
        metadata = benchmark.get("metadata")
        suite = config.get("suite")
        if not isinstance(metadata, dict) or not isinstance(suite, str):
            raise BundleError("embedded benchmark custody is incomplete")
        if metadata.get("suite") != suite:
            raise BundleError("embedded benchmark suite does not match config")
        traces = [
            _parse_json(line, "traces.jsonl")
            for line in (source_root / "traces.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        if any(not isinstance(trace, dict) for trace in traces):
            raise BundleError("raw trace inventory is invalid")
        expected_metrics = _recompute_bundle_metrics(
            config.get("scoring_profile"),
            config.get("family"),
            benchmark.get("data"),
            traces,
        )
        expected_metric_bytes = _canonical(expected_metrics)
        if expected_metric_bytes != (source_root / "metrics.json").read_bytes():
            raise BundleError("reproduction mismatch: metrics.json")

        final.mkdir()
        inventory = manifest["artifacts"]["files"]
        canonical_json = {
            "adapter-manifest.json",
            "baseline-manifest.json",
            "canonical-replay.json",
            "environment.json",
            "fixture-manifest.json",
            "generator-manifest.json",
            "prompt-manifest.json",
            "result.json",
            "scorer-manifest.json",
        }
        for entry in inventory:
            name = entry["path"]
            source_file = source_root / name
            target = final / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == "metrics.json":
                target.write_bytes(expected_metric_bytes)
            elif name in canonical_json:
                target.write_bytes(_canonical(_load_json(source_file)))
            else:
                shutil.copyfile(source_file, target)
            shutil.copymode(source_file, target, follow_symlinks=False)
            if not _files_equal(target, source_file):
                raise BundleError(f"reproduction mismatch: {name}")
        (final / "reproducibility-manifest.json").write_bytes(
            _canonical(manifest)
        )
        result = verify_reproducibility_bundle(final)
        if os.path.lexists(destination_root):
            raise FileExistsError(
                f"refusing to overwrite bundle: {destination_root}"
            )
        _publish_directory_noreplace(final, destination_root)
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
    if (root / "reproducibility-manifest.json").exists():
        return verify_reproducibility_bundle(root)
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
    allowed_profile = {
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
    }.get(profile)
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
    if profile == "smoke-hit-at-k-v1" and measured.get("interval", {}).get(
        "method"
    ) != method:
        raise BundleError("wrong interval-family metadata")
    if profile == "smoke-hit-at-k-v1" and measured.get("metric") != "hit_at_k":
        raise BundleError("deterministic retrieval metric must be hit_at_k")
    expected_metrics = _recompute_bundle_metrics(
        profile, family, benchmark.get("data"), traces
    )
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
    if (Path(source) / "reproducibility-manifest.json").exists():
        return reproduce_reproducibility_bundle(source, destination)
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


def _recompute_bundle_metrics(
    profile: str,
    family: str,
    benchmark: Any,
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    if profile != "smoke-hit-at-k-v1":
        from eval.public.scoring import ScoringError, score_profile

        try:
            return score_profile(profile, _scoring_labels(benchmark), traces)
        except (ScoringError, ValueError, TypeError, AttributeError, KeyError) as exc:
            raise BundleError(
                "generalized scoring profile recomputation failed"
            ) from exc
    if family != "deterministic-retrieval":
        raise BundleError("smoke scoring profile has the wrong metric family")
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
    k = benchmark["k"]
    successes = sum(
        bool(
            set(trace["ranked_retrieved_hits"][:k])
            & set(gold_by_question[trace["question_id"]])
        )
        for trace in traces
    )
    expected = wilson_interval(successes, len(traces)).as_dict()
    return {
        "family": family,
        "metric": "hit_at_k",
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
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
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
