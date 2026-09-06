"""Canonical public benchmark bundle custody, verification, and reproduction."""

from __future__ import annotations

import hashlib
import errno
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

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
_LEGACY_README = (
    b"# PBPP development bundle\n\n"
    b"This development artifact is non-publishable, not headline eligible, and "
    b"is not an independent external reproduction. Run `./reproduce.sh DEST`.\n"
)
_LEGACY_REPRODUCE_SCRIPT = (
    b'#!/bin/sh\nset -eu\ntest "$#" -eq 1 || { echo "usage: $0 DEST" >&2; '
    b'exit 2; }\nuv run --locked mneme eval-public --reproduce-bundle '
    b'"$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" --out-dir "$1"\n'
)
SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AIza[A-Za-z0-9_-]{35}|(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"sk-(?:(?:proj|svcacct)-[A-Za-z0-9_-]{16,}|[A-Za-z0-9]{20,})|"
    r"sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"(?i:bearer|basic)\s+[A-Za-z0-9._~+/-]{20,}={0,2}|"
    r"[A-Za-z][A-Za-z0-9+.-]{0,31}://"
    r"[^/\s:@]{1,256}:[^/\s@]{1,256}@|"
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
REPRODUCIBILITY_BUNDLE_SCHEMA_DIALECT = (
    "https://json-schema.org/draft/2020-12/schema"
)
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
_REPRO_MANIFEST_ARTIFACTS = {
    "adapter": ("adapter", "adapter.json"),
    "baseline": ("baseline", "baseline.json"),
    "benchmark": ("benchmark", "benchmark-ref.json"),
    "dataset_split": ("dataset-split", "dataset-split.json"),
    "difference": ("difference", "difference.json"),
    "fidelity": ("fidelity", "fidelity.json"),
    "fixture": ("fixture", "fixture-ref.json"),
    "generator": ("generator", "generator.json"),
    "judge": ("judge", "judge-ref.json"),
    "model": ("model", "model-ref.json"),
    "parent": ("parent", "parent.json"),
    "prompt": ("prompt", "prompt-ref.json"),
    "reader": ("reader", "reader-ref.json"),
    "scorer": ("scorer", "scorer.json"),
}
_REPRO_CORE_ARTIFACTS = {
    REPRODUCIBILITY_MANIFEST_NAME,
    "build.json",
    "bundle-manifest.json",
    "canonical-replay.json",
    "config.json",
    "environment.json",
    "metrics.json",
    "result.json",
    "traces.jsonl",
    "uv.lock",
}
_REPRO_LEDGER_ARTIFACTS = {
    "ledger.jsonl",
    "ledger.jsonl.head.json",
    "ledger-public.pem",
}
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
_REPRO_CONFIG_ARTIFACT_FIELDS = {
    "family",
    "interval_method",
    "k",
    "locale",
    "scoring_profile",
    "suite",
    "timezone",
}
_REPRO_BUILD_ARTIFACT_FIELDS = {
    "candidate_git_sha",
    "dirty",
    "environment_contract",
    "lockfile",
    "system_seam",
    "toolchain",
    "version",
}
_REPRO_ENVIRONMENT_ARTIFACT_FIELDS = {
    "allowlist",
    "dependency_versions",
    "locale",
    "platform",
    "runtime",
    "timezone",
    "wheelhouse_digest",
}
_REPRO_ENVIRONMENT_VARIABLES = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SystemRoot",
    "TEMP",
    "TMP",
    "TZ",
    "UV_CACHE_DIR",
    "UV_OFFLINE",
    "WINDIR",
}
_NAMED_DIGEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*@sha256:[0-9a-f]{64}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_REPRO_JSON_DEPTH = 64
_MAX_REPRO_FILE_BYTES = 16 * 1024 * 1024
_MAX_REPRO_BUNDLE_BYTES = 1024 * 1024 * 1024
_MAX_REPRO_FILES = 4097  # schema maximum plus the reproducibility manifest
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
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 4


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

    def project(value: object, *, strip_volatile_fields: bool = False) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise BundleError("non-finite numbers are forbidden")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise BundleError("canonical replay map keys must be strings")
            return {
                key: project(item)
                for key, item in value.items()
                if not (
                    strip_volatile_fields
                    and key in CANONICAL_REPLAY_VOLATILE_FIELDS
                )
            }
        if isinstance(value, list):
            return [project(item) for item in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        raise BundleError(f"canonical replay contains ambiguous value: {type(value).__name__}")

    try:
        projection = {
            key: project(item, strip_volatile_fields=key == "volatile")
            for key, item in payload.items()
        }
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


def _assert_reproduction_checkout(expected_sha: str, expected_lockfile: bytes) -> None:
    """Require a detached, clean checkout at the exact bundle-bound commit."""
    if not isinstance(expected_sha, str) or _HEX_COMMIT.fullmatch(expected_sha) is None:
        raise BundleError("bound commit is unavailable")
    git = shutil.which("git")
    if git is None:
        raise BundleError("reproduction checkout is unavailable")
    git_environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    if os.name == "nt" and "SystemRoot" in os.environ:
        git_environment["SystemRoot"] = os.environ["SystemRoot"]

    def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [git, *arguments],
                cwd=Path.cwd(),
                env=git_environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BundleError("reproduction checkout is unavailable") from exc

    result = run_git("rev-parse", "--verify", "HEAD^{commit}")
    if result.returncode != 0:
        raise BundleError("reproduction checkout is unavailable")
    actual = result.stdout.strip()
    if actual != expected_sha:
        raise BundleError("reproduction checkout does not match bound commit")
    detached = run_git("symbolic-ref", "-q", "HEAD")
    if detached.returncode == 0:
        raise BundleError("reproduction checkout must be detached")
    if detached.returncode != 1:
        raise BundleError("reproduction checkout is unavailable")
    dirty = run_git("status", "--porcelain=v1", "--untracked-files=all")
    if dirty.returncode != 0 or dirty.stdout:
        raise BundleError("reproduction checkout is dirty")
    checkout_lockfile, _ = _read_inventory_file(Path.cwd() / "uv.lock")
    if checkout_lockfile != expected_lockfile:
        raise BundleError("reproduction checkout lockfile does not match bundle")


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


def _require_disclosed_string(value: object, label: str) -> str:
    disclosed = _require_nonempty_string(value, label)
    if disclosed.strip().casefold() == "unknown":
        raise BundleError(f"unknown {label}")
    return disclosed


def _require_enum(value: object, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise BundleError(f"unknown {label}")
    return str(value)


def _validate_repro_schema(manifest: object) -> None:
    try:
        schema_bytes, _ = _read_inventory_file(
            REPRODUCIBILITY_BUNDLE_SCHEMA_PATH, allow_hardlinks=True
        )
        schema = _parse_json(schema_bytes.decode("utf-8"), "reproducibility schema")
        _json_depth(schema)
    except (OSError, UnicodeDecodeError, BundleError) as exc:
        raise BundleError("reproducibility schema is invalid") from exc
    if not isinstance(schema, dict) or (
        schema.get("$schema") != REPRODUCIBILITY_BUNDLE_SCHEMA_DIALECT
        or schema.get("$id") != REPRODUCIBILITY_BUNDLE_SCHEMA_VERSION
    ):
        raise BundleError("reproducibility schema identity is invalid")
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(manifest)
    except SchemaError as exc:
        raise BundleError("reproducibility schema is invalid") from exc
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
    expected_name, expected_path = _REPRO_MANIFEST_ARTIFACTS[label]
    if (
        not isinstance(value, str)
        or value.split("@sha256:", 1)[0] != expected_name
        or expected_path not in payloads
        or hashlib.sha256(payloads[expected_path]).hexdigest() != digest
    ):
        raise BundleError(f"{label} digest is not bound to its named artifact")
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
    if build.get("toolchain") != "uv":
        raise BundleError("toolchain must be uv")
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
    _require_disclosed_string(environment.get("platform"), "environment platform")
    _require_disclosed_string(environment.get("runtime"), "environment runtime")
    if environment.get("wheelhouse_digest") is not None:
        _require_sha256_digest(
            environment.get("wheelhouse_digest"), "wheelhouse_digest"
        )
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
    for field in (
        "software_license",
        "data_license",
        "redistribution",
        "pii",
        "consent",
        "takedown",
    ):
        _require_disclosed_string(rights.get(field), f"rights {field}")
    if rights.get("disclosure_state") != "disclosed":
        raise BundleError("missing rights disclosure")
    custody = _closed_object(payload.get("custody"), ("class", "declaration"), "custody")
    _require_enum(custody.get("class"), _REPRO_CUSTODY_CLASSES, "custody")
    _require_disclosed_string(custody.get("declaration"), "custody declaration")
    operator = _closed_object(
        payload.get("operator"),
        ("identity", "role", "signer_role", "disclosure_state"),
        "operator",
    )
    _require_disclosed_string(operator.get("identity"), "operator identity")
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
        expected_media_type = (
            "application/jsonl"
            if path.endswith(".jsonl")
            else "application/x-pem-file"
            if path.endswith(".pem")
            else "text/plain"
            if path == "uv.lock"
            else "application/json"
            if path.endswith(".json")
            else None
        )
        if (
            expected_media_type is None
            or item.get("canonicalization") != "raw-bytes"
            or (
                item.get("media_type") != expected_media_type
            )
        ):
            raise BundleError("inventory media type or canonicalization mismatch")
        _require_sha256_digest(item.get("sha256"), "inventory digest")
    if [str(entry["path"]) for entry in hashes] != sorted(seen_paths):
        raise BundleError("inventory paths must use canonical sorted order")
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


def _read_inventory_file(
    path: Path, *, allow_hardlinks: bool = False
) -> tuple[bytes, int]:
    """Read one stable, bounded regular file; inventories must be single-link."""
    try:
        path_stat = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or (not allow_hardlinks and path_stat.st_nlink != 1)
            or path_stat.st_size > _MAX_REPRO_FILE_BYTES
        ):
            raise BundleError("bundle files must be bounded regular non-hardlinks")
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or (not allow_hardlinks and opened_stat.st_nlink != 1)
                or _stable_file_state(opened_stat) != _stable_file_state(path_stat)
            ):
                raise BundleError(f"bundle file changed before reading: {path.name}")
            payload = handle.read(_MAX_REPRO_FILE_BYTES + 1)
            final_stat = os.fstat(handle.fileno())
        current_stat = path.stat(follow_symlinks=False)
    except BundleError:
        raise
    except OSError as exc:
        raise BundleError(f"bundle file cannot be read safely: {path.name}") from exc
    if (
        len(payload) != opened_stat.st_size
        or len(payload) > _MAX_REPRO_FILE_BYTES
        or _stable_file_state(final_stat) != _stable_file_state(opened_stat)
        or _stable_file_state(current_stat) != _stable_file_state(final_stat)
    ):
        raise BundleError(f"bundle file changed while reading: {path.name}")
    return payload, len(payload)


def _stable_file_state(metadata: os.stat_result) -> tuple[int, int, int, int]:
    """Return identity and same-size mutation signals for one file snapshot."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _read_reproducibility_manifest(root: Path) -> tuple[bytes, dict[str, Any]]:
    """Read, parse, and validate one stable manifest inode snapshot."""
    manifest_path = root / REPRODUCIBILITY_MANIFEST_NAME
    try:
        manifest_bytes, _ = _read_inventory_file(manifest_path)
        loaded = _parse_bounded_json(
            manifest_bytes.decode("utf-8"), REPRODUCIBILITY_MANIFEST_NAME
        )
    except UnicodeDecodeError as exc:
        raise BundleError("reproducibility manifest is not UTF-8") from exc
    except BundleError as exc:
        cause = exc.__cause__
        if isinstance(cause, ValueError) and "duplicate" in str(cause):
            raise BundleError("duplicate JSON key in reproducibility manifest") from exc
        raise
    if manifest_bytes != _canonical(loaded):
        raise BundleError("reproducibility manifest bytes must be canonical")
    return manifest_bytes, _validate_reproducibility_manifest(loaded)


def _inventory_bytes(
    root: Path,
    manifest: dict[str, Any],
    *,
    manifest_bytes: bytes | None = None,
) -> dict[str, bytes]:
    hashes = manifest["hashes"]
    listed = [entry["path"] for entry in hashes]
    if len(listed) != len(set(listed)):
        raise BundleError("duplicate normalized path")
    listed_set = set(listed)
    payloads: dict[str, bytes] = {}
    scanned: dict[str, bytes] = {}
    total_size = 0
    for entry_number, entry in enumerate(root.iterdir(), start=1):
        if entry_number > _MAX_REPRO_FILES:
            raise BundleError("bundle exceeds the closed file-count bound")
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            raise BundleError(f"links and non-files are forbidden: {entry.name}")
        if entry.resolve().parent != root.resolve():
            raise BundleError(f"path escapes bundle: {entry.name}")
        if entry.name == REPRODUCIBILITY_MANIFEST_NAME and manifest_bytes is not None:
            payload, entry_size = manifest_bytes, len(manifest_bytes)
        else:
            payload, entry_size = _read_inventory_file(entry)
        total_size += entry_size
        if total_size > _MAX_REPRO_BUNDLE_BYTES:
            raise BundleError("bundle exceeds the closed aggregate size bound")
        if SECRET.search(payload.decode("utf-8", errors="replace")):
            raise BundleError("secret-like material detected")
        scanned[entry.name] = payload
    expected = listed_set | {REPRODUCIBILITY_MANIFEST_NAME}
    extras = set(scanned) - expected
    if extras or any(name not in scanned for name in expected):
        raise BundleError("inventory mismatch")
    payloads = {name: scanned[name] for name in expected}
    for name, payload in payloads.items():
        text = payload.decode("utf-8", errors="replace")
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                _parse_bounded_json(line, name)
        elif name.endswith(".json"):
            _parse_bounded_json(text, name)
    for entry in hashes:
        path = str(entry["path"])
        payload = payloads[path]
        if len(payload) != entry["size"] or _sha256_ref(payload) != entry["sha256"]:
            raise BundleError(f"digest mismatch: {path}")
    return payloads


def _validate_bound_lockfile(raw: bytes) -> None:
    """Require a parseable uv lock that contains this verifier's runtime deps."""
    try:
        lock = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BundleError("bound uv.lock is invalid") from exc
    packages = lock.get("package")
    if (
        type(lock.get("version")) is not int
        or lock.get("version") != 1
        or type(lock.get("revision")) is not int
        or lock.get("revision") < 1
        or not isinstance(lock.get("requires-python"), str)
        or not lock.get("requires-python").strip()
        or not isinstance(packages, list)
        or not packages
    ):
        raise BundleError("bound uv.lock contract is invalid")
    projects = [
        package
        for package in packages
        if isinstance(package, dict) and package.get("name") == "mnemosyne-memory"
    ]
    if len(projects) != 1 or projects[0].get("source") != {"editable": "."}:
        raise BundleError("bound uv.lock does not identify the Mnemosyne project")
    dependencies = projects[0].get("dependencies")
    if not isinstance(dependencies, list):
        raise BundleError("bound uv.lock project dependencies are invalid")
    dependency_names = {
        dependency.get("name")
        for dependency in dependencies
        if isinstance(dependency, dict)
    }
    runtime_dependencies = {"cryptography", "jsonschema"}
    if not runtime_dependencies <= dependency_names:
        raise BundleError("bound uv.lock omits verifier runtime dependencies")
    resolved_dependencies = {
        package.get("name")
        for package in packages
        if (
            isinstance(package, dict)
            and package.get("name") in runtime_dependencies
            and isinstance(package.get("version"), str)
            and bool(package["version"].strip())
            and isinstance(package.get("source"), dict)
            and bool(package["source"])
        )
    }
    if not runtime_dependencies <= resolved_dependencies:
        raise BundleError("bound uv.lock omits resolved verifier packages")


def _validate_bound_bundle_manifest(payloads: dict[str, bytes]) -> None:
    """Validate the nested v1 inventory against authenticated source artifacts."""
    manifest = _load_inventory_json(payloads, "bundle-manifest.json")
    if not isinstance(manifest, dict) or set(manifest) != {"files", "version"}:
        raise BundleError("bound bundle manifest is invalid")
    files = manifest.get("files")
    excluded = {
        REPRODUCIBILITY_MANIFEST_NAME,
        "bundle-manifest.json",
        "ledger.jsonl",
        "ledger.jsonl.head.json",
        "ledger-public.pem",
        "result.json",
    }
    expected = set(payloads) - excluded
    if (
        type(manifest.get("version")) is not int
        or manifest.get("version") != 1
        or not isinstance(files, dict)
        or set(files) != expected
    ):
        raise BundleError("bound bundle manifest inventory mismatch")
    for name, digest in files.items():
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or hashlib.sha256(payloads[name]).hexdigest() != digest
        ):
            raise BundleError(f"bound bundle manifest digest mismatch: {name}")


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
    _require_nonempty_string(config.get("suite"), "suite")
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
    question_ids: set[str] = set()
    for trace in traces:
        if not isinstance(trace, dict):
            raise BundleError("metrics do not recompute from traces")
        question_id = trace.get("question_id")
        hits = trace.get("ranked_retrieved_hits")
        gold = trace.get("gold_references")
        stored = trace.get("stored_records")
        answer = trace.get("answer")
        if (
            not isinstance(question_id, str)
            or not question_id.strip()
            or question_id in question_ids
        ):
            raise BundleError("trace question IDs must be unique nonempty strings")
        question_ids.add(question_id)
        if trace.get("scoring_family") != "deterministic-retrieval":
            raise BundleError("trace scoring family does not match the bound scorer")
        if (
            not isinstance(hits, list)
            or not isinstance(gold, list)
            or not gold
            or any(
                not isinstance(item, str) or not item.strip()
                for item in [*hits, *gold]
            )
        ):
            raise BundleError("retrieval trace identifiers are malformed")
        unique_hits = set(hits)
        if len(hits) != len(unique_hits) or len(gold) != len(set(gold)):
            raise BundleError("duplicate ranked retrieved ids")
        if (
            not isinstance(stored, list)
            or any(not isinstance(item, str) or not item.strip() for item in stored)
            or len(stored) != len(set(stored))
        ):
            raise BundleError("stored trace population is malformed")
        stored_ids = set(stored)
        if not set(hits) <= stored_ids or not set(gold) <= stored_ids:
            raise BundleError("retrieval trace references records outside its population")
        if answer is not None and (
            not isinstance(answer, str) or answer not in stored_ids
        ):
            raise BundleError("retrieval trace answer is outside its population")
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
    aborts: int,
) -> dict[str, Any]:
    if not isinstance(measured, dict):
        raise BundleError("missing metrics")
    k = _bound_repro_k(config)
    version = _bound_repro_scoring_profile(config)
    successes, total = _score_repro_traces(traces, k)
    recomputed = _measured_from_repro_score(successes, total)
    expected_value = recomputed["value"]
    expected_interval = recomputed["interval"]
    if _canonical(measured) != _canonical(recomputed):
        raise BundleError("metrics do not recompute from traces")
    if not isinstance(manifest_metrics, list):
        raise BundleError("missing metrics")
    measured_interval = measured.get("interval", {})
    if (
        not isinstance(measured_interval, dict)
        or set(measured_interval) != set(expected_interval)
        or any(
            measured_interval.get(key) != expected_interval[key]
            for key in expected_interval
        )
    ):
        raise BundleError("intervals do not recompute from traces")
    expected_manifest_metrics = [
        {
            "aborted_count": aborts,
            "confidence_level": 0.95,
            "denominator": total,
            "exclusions": [],
            "failed_count": 0,
            "family": "retrieval",
            "interval": {
                "high": expected_interval["high"],
                "low": expected_interval["low"],
            },
            "missing_count": 0,
            "name": "hit_at_k",
            "not_measured_count": 0,
            "numerator": successes,
            "sample_count": total,
            "uncertainty_method": "wilson",
            "uncertainty_parameters": {"z": 1.96},
            "unit": "ratio",
            "unsupported_count": 0,
            "value": expected_value,
            "version": version,
        }
    ]
    if _canonical(manifest_metrics) != _canonical(expected_manifest_metrics):
        raise BundleError("metrics do not recompute from traces")
    if not isinstance(manifest_intervals, list):
        raise BundleError("missing intervals")
    expected_manifest_intervals = [
        {
            "confidence_level": 0.95,
            "high": expected_interval["high"],
            "low": expected_interval["low"],
            "method": expected_interval["method"],
            "metric": "hit_at_k",
        }
    ]
    if _canonical(manifest_intervals) != _canonical(expected_manifest_intervals):
        raise BundleError("intervals do not recompute from traces")
    return recomputed


def _verify_reproducibility_bundle(root: Path) -> dict[str, Any]:
    _reject_reproducibility_link_path(root)
    if (
        not root.is_dir()
        or root.is_symlink()
        or getattr(root, "is_junction", lambda: False)()
    ):
        raise BundleError("bundle must be a real directory, not a link")
    root_identity = _owned_directory_identity(root)
    if not REPRODUCIBILITY_BUNDLE_SCHEMA_PATH.is_file():
        raise BundleError("reproducibility schema is missing")
    manifest_bytes, manifest = _read_reproducibility_manifest(root)
    payloads = _inventory_bytes(root, manifest, manifest_bytes=manifest_bytes)
    for required in ("traces.jsonl", "config.json", "build.json", "result.json", "bundle-manifest.json"):
        if required not in payloads:
            raise BundleError(f"missing {required}")
    config_payload = _load_inventory_json(payloads, "config.json")
    build_payload = _load_inventory_json(payloads, "build.json")
    environment_payload = _load_inventory_json(payloads, "environment.json")
    if (
        not isinstance(config_payload, dict)
        or bool(set(config_payload) - _REPRO_CONFIG_ARTIFACT_FIELDS)
        or bool((_REPRO_CONFIG_ARTIFACT_FIELDS - {"k"}) - set(config_payload))
        or any(
            _canonical(config_payload.get(field))
            != _canonical(manifest["config"][field])
            for field in ("locale", "timezone")
        )
    ):
        raise BundleError("config declaration does not match bound artifact")
    if (
        not isinstance(build_payload, dict)
        or set(build_payload) != _REPRO_BUILD_ARTIFACT_FIELDS
        or type(build_payload.get("version")) is not int
        or build_payload.get("version") != 1
        or any(
            _canonical(build_payload.get(field))
            != _canonical(manifest["build"][field])
            for field in (
                "candidate_git_sha",
                "dirty",
                "environment_contract",
                "toolchain",
            )
        )
    ):
        raise BundleError("build declaration does not match bound artifact")
    _require_disclosed_string(build_payload.get("system_seam"), "system seam")
    if manifest["rights"]["source_revision"] != manifest["build"]["candidate_git_sha"]:
        raise BundleError("rights source revision does not match bound commit")
    if build_payload.get("lockfile") != "uv.lock":
        raise BundleError("build lockfile declaration does not match bound artifact")
    if (
        not isinstance(environment_payload, dict)
        or set(environment_payload) != _REPRO_ENVIRONMENT_ARTIFACT_FIELDS
        or environment_payload.get("dependency_versions") != {"uv": "locked"}
        or any(
            _canonical(environment_payload.get(field))
            != _canonical(manifest["environment"][field])
            for field in (
                "allowlist",
                "locale",
                "timezone",
                "platform",
                "runtime",
                "wheelhouse_digest",
            )
        )
    ):
        raise BundleError("environment declaration does not match bound artifact")
    environment_allowlist = environment_payload["allowlist"]
    if (
        not isinstance(environment_allowlist, list)
        or environment_allowlist != sorted(environment_allowlist)
        or any(name not in _REPRO_ENVIRONMENT_VARIABLES for name in environment_allowlist)
    ):
        raise BundleError("environment allowlist is not closed and canonical")
    if manifest["build"]["build_fingerprint"] != _sha256_ref(payloads["build.json"]):
        raise BundleError("build_fingerprint digest mismatch")
    if manifest["config"]["config_digest"] != _sha256_ref(payloads["config.json"]):
        raise BundleError("config_digest digest mismatch")
    if manifest["traces"]["trace_index_digest"] != _sha256_ref(payloads["traces.jsonl"]):
        raise BundleError("trace_index_digest digest mismatch")
    result = _load_inventory_json(payloads, "result.json")
    if payloads["result.json"] != _canonical(result):
        raise BundleError("result.json bytes must be canonical")
    if manifest["result_ref"] != f"result-v2@sha256:{hashlib.sha256(payloads['result.json']).hexdigest()}":
        raise BundleError("result digest mismatch")
    if "uv.lock" not in payloads:
        raise BundleError("missing lockfile")
    if manifest["build"]["lockfile"] != f"uv.lock@sha256:{hashlib.sha256(payloads['uv.lock']).hexdigest()}":
        raise BundleError("lockfile digest mismatch")
    _validate_bound_lockfile(payloads["uv.lock"])
    refs = manifest["manifests"]
    for key, ref in refs.items():
        expected_kind, artifact_path = _REPRO_MANIFEST_ARTIFACTS[key]
        if ref is None:
            if artifact_path in payloads:
                raise BundleError(f"unreferenced {key} artifact is forbidden")
            continue
        _require_bound_digest(ref, key, payloads)
        artifact = _load_inventory_json(payloads, artifact_path)
        if not isinstance(artifact, dict) or artifact.get("kind") != expected_kind:
            raise BundleError(f"{key} artifact kind does not match its manifest role")
    scorer_artifact = _load_inventory_json(payloads, "scorer.json")
    benchmark_artifact = _load_inventory_json(payloads, "benchmark-ref.json")
    if scorer_artifact.get("id") != config_payload.get("scoring_profile"):
        raise BundleError("scorer artifact does not match bound scoring profile")
    if benchmark_artifact.get("id") != config_payload.get("suite"):
        raise BundleError("benchmark artifact does not match bound suite")
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
    if result.get("lineage") != manifest["lineage"]:
        raise BundleError("result lineage does not match manifest")
    if manifest["track_kind"] == "OFFICIAL-UPSTREAM":
        fidelity_artifact = _load_inventory_json(payloads, "fidelity.json")
        fidelity_lineage = manifest["lineage"]["fidelity"]
        if any(
            fidelity_artifact.get(field) != value
            for field, value in fidelity_lineage.items()
            if field == "upstream_protocol_digest" or field in fidelity_artifact
        ):
            raise BundleError("fidelity artifact does not match result lineage")
    elif manifest["track_kind"] == "ENHANCED-SUCCESSOR":
        parent_artifact = _load_inventory_json(payloads, "parent.json")
        if parent_artifact.get("record_id") != manifest["lineage"][
            "parent_official_record_id"
        ]:
            raise BundleError("parent artifact does not match result lineage")
    if result.get("run_commit") != manifest["build"]["candidate_git_sha"]:
        raise BundleError("result run_commit does not match bound commit")
    result_profile = result.get("run_profile")
    result_identity = result.get("identity")
    if (
        not isinstance(result_profile, dict)
        or result_profile.get("seeds") != manifest["traces"]["seed_records"]
        or result_profile.get("retries") != manifest["traces"]["retries"]
        or result_profile.get("aborts") != manifest["traces"]["aborts"]
        or not isinstance(result_identity, dict)
        or result_identity.get("seed") not in manifest["traces"]["seed_records"]
    ):
        raise BundleError("result run profile does not match trace custody")
    if "canonical-replay.json" not in payloads:
        raise BundleError("canonical replay artifact is missing")
    replay = _load_inventory_json(payloads, "canonical-replay.json")
    expected = manifest["canonical_replay"]
    if (
        not isinstance(expected, dict)
        or expected.get("digest") != canonical_replay_digest(replay)
        or expected.get("suite") != replay.get("suite")
        or expected.get("seed_records") != replay.get("seed_records")
        or expected.get("seed_records") != manifest["traces"]["seed_records"]
    ):
        raise BundleError("canonical replay digest mismatch")
    replay_build = replay.get("build") if isinstance(replay, dict) else None
    replay_config = replay.get("config") if isinstance(replay, dict) else None
    if (
        not isinstance(replay_build, dict)
        or replay_build.get("candidate_git_sha")
        != manifest["build"]["candidate_git_sha"]
        or replay_build.get("system_seam") != build_payload.get("system_seam")
        or any(
            _canonical(replay_build[field]) != _canonical(build_payload[field])
            for field in set(replay_build) & set(build_payload)
        )
    ):
        raise BundleError("canonical replay build custody mismatch")
    if (
        not isinstance(replay_config, dict)
        or any(
            replay_config.get(field) != manifest["config"][field]
            for field in ("locale", "timezone")
        )
        or any(
            _canonical(replay_config[field]) != _canonical(config_payload[field])
            for field in set(replay_config) & set(config_payload)
        )
    ):
        raise BundleError("canonical replay config custody mismatch")
    ledger_names = tuple(sorted(_REPRO_LEDGER_ARTIFACTS))
    present_ledger_names = {name for name in ledger_names if name in payloads}
    if manifest.get("ledger_ref") is None:
        if present_ledger_names:
            raise BundleError("ledger artifacts require a verified ledger_ref")
    else:
        from leaderboard.ledger import LedgerError
        from leaderboard.ledger import _canonical as ledger_canonical
        from leaderboard.ledger import verify_ledger

        if present_ledger_names != set(ledger_names):
            raise BundleError("missing ledger inclusion receipt")
        # ``verify_ledger`` uses a lock file and therefore cannot safely run
        # against an untrusted, supposedly read-only bundle.  Verify the exact
        # inventory-bound bytes in a private snapshot instead.  This also
        # prevents a pathname swap after ``_inventory_bytes`` hashed the files.
        with tempfile.TemporaryDirectory(prefix="mneme-repro-ledger-") as temporary:
            snapshot = Path(temporary)
            for name in ledger_names:
                (snapshot / name).write_bytes(payloads[name])
            try:
                entries = verify_ledger(
                    snapshot / "ledger.jsonl", snapshot / "ledger-public.pem"
                )
            except LedgerError as exc:
                raise BundleError("ledger verification failed") from exc
        result_matches = [
            entry
            for entry in entries
            if (
                isinstance(entry, dict)
                and _canonical(entry.get("result")) == _canonical(result)
            )
        ]
        if not result_matches:
            raise BundleError("ledger result reference mismatch")
        matched = [
            entry
            for entry in result_matches
            if entry.get("run_id") == result_identity.get("run_id")
        ]
        if not matched:
            raise BundleError("ledger run_id does not match result identity")
        superseded_ids = {
            entry.get("supersedes")
            for entry in entries
            if isinstance(entry, dict) and entry.get("status") == "superseded"
        }
        matched = [entry for entry in matched if entry.get("entry_id") not in superseded_ids]
        if not matched:
            raise BundleError("ledger result inclusion receipt is superseded")
        if not any(
            manifest["ledger_ref"]
            == f"ledger-entry@sha256:{hashlib.sha256(ledger_canonical(entry)).hexdigest()}"
            for entry in matched
        ):
            raise BundleError("ledger_ref digest mismatch")
    expected_artifacts = _REPRO_CORE_ARTIFACTS | {
        _REPRO_MANIFEST_ARTIFACTS[key][1]
        for key, ref in refs.items()
        if ref is not None
    }
    if manifest.get("ledger_ref") is not None:
        expected_artifacts |= _REPRO_LEDGER_ARTIFACTS
    if set(payloads) - expected_artifacts:
        raise BundleError("reproducibility bundle contains an unexpected artifact")
    try:
        trace_lines = payloads["traces.jsonl"].decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise BundleError("traces.jsonl is not UTF-8") from exc
    traces = [_parse_bounded_json(line, "traces.jsonl") for line in trace_lines if line]
    if "metrics.json" not in payloads:
        raise BundleError("missing metrics")
    recomputed = _recompute_repro_metrics(
        traces,
        _load_inventory_json(payloads, "metrics.json"),
        manifest.get("metrics"),
        manifest.get("intervals"),
        config=_load_inventory_json(payloads, "config.json"),
        aborts=manifest["traces"]["aborts"],
    )
    interval = recomputed["interval"]
    expected_result_metrics = [
        {
            "confidence_interval": {
                "high": interval["high"],
                "low": interval["low"],
            },
            "family": "retrieval",
            "name": "hit_at_k",
            "unit": "ratio",
            "value": recomputed["value"],
        }
    ]
    if _canonical(result.get("metrics")) != _canonical(expected_result_metrics):
        raise BundleError("result metrics do not match recomputed traces")
    _validate_bound_bundle_manifest(payloads)
    publication = manifest["publication"]
    _assert_inventory_snapshot(root, payloads)
    _assert_directory_identity(root, root_identity, "bundle")
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


def _publish_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing an existing path."""
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


def _owned_directory_identity(path: Path) -> tuple[int, int]:
    """Capture the filesystem identity of one process-created directory."""
    metadata = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or getattr(path, "is_junction", lambda: False)()
    ):
        raise BundleError("private reproduction path is not a directory")
    return metadata.st_dev, metadata.st_ino


def _assert_directory_identity(
    path: Path, identity: tuple[int, int], label: str
) -> None:
    """Require an inspected directory to remain bound to its original inode."""
    try:
        current = _owned_directory_identity(path)
    except (OSError, BundleError) as exc:
        raise BundleError(f"{label} directory changed while reading") from exc
    if current != identity:
        raise BundleError(f"{label} directory changed while reading")


def _remove_owned_directory(path: Path, identity: tuple[int, int]) -> None:
    """Remove a private directory only while its original inode is still named."""
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        return
    if (
        stat.S_ISDIR(metadata.st_mode)
        and not path.is_symlink()
        and not getattr(path, "is_junction", lambda: False)()
        and (metadata.st_dev, metadata.st_ino) == identity
    ):
        shutil.rmtree(path, ignore_errors=True)


def _reproduce_reproducibility_bundle(source: Path, destination: Path) -> dict[str, Any]:
    _reject_reproducibility_link_path(source)
    if (
        not source.is_dir()
        or source.is_symlink()
        or getattr(source, "is_junction", lambda: False)()
    ):
        raise BundleError("bundle must be a real directory, not a link")
    destination = _absolute_normalized_path(destination)
    _reject_reproducibility_link_path(destination)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_reproducibility_link_path(destination)
    snapshot = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-source-", dir=destination.parent)
    )
    snapshot_identity = _owned_directory_identity(snapshot)
    try:
        temp = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
        )
        temp_identity = _owned_directory_identity(temp)
    except BaseException:
        _remove_owned_directory(snapshot, snapshot_identity)
        raise
    try:
        manifest_bytes, source_manifest = _read_reproducibility_manifest(source)
        payloads = _inventory_bytes(
            source, source_manifest, manifest_bytes=manifest_bytes
        )
        (snapshot / REPRODUCIBILITY_MANIFEST_NAME).write_bytes(manifest_bytes)
        for name, payload in payloads.items():
            (snapshot / name).write_bytes(payload)

        verified = _verify_reproducibility_bundle(snapshot)
        _assert_reproduction_checkout(
            str(verified["run_commit"]), payloads["uv.lock"]
        )
        owned = [
            str(entry["path"])
            for entry in source_manifest["hashes"]
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        ] + [REPRODUCIBILITY_MANIFEST_NAME]
        for name in owned:
            if name == "metrics.json":
                continue
            src = snapshot / name
            if src.is_symlink() or not src.is_file():
                raise BundleError(f"links and non-files are forbidden: {name}")
            shutil.copyfile(src, temp / name, follow_symlinks=False)
        config = _load_json(temp / "config.json")
        traces = [
            _parse_bounded_json(line, "traces.jsonl")
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
            aborts=source_manifest["traces"]["aborts"],
        )
        _write_json(temp / "metrics.json", recomputed)
        _verify_reproducibility_bundle(temp)
        for name in owned:
            reproduced, _ = _read_inventory_file(temp / name)
            if reproduced != payloads[name]:
                raise BundleError(f"reproduction mismatch: {name}")
        _reject_reproducibility_link_path(destination)
        _publish_directory_noreplace(temp, destination)
        return verified
    except BaseException:
        _remove_owned_directory(temp, temp_identity)
        raise
    finally:
        _remove_owned_directory(snapshot, snapshot_identity)


def write_bundle(
    destination: Path,
    *,
    benchmark: dict[str, Any],
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    traces: list[dict[str, Any]],
    candidate_manifest_path: Path | str | None = None,
) -> None:
    destination = _absolute_normalized_path(destination)
    _reject_reproducibility_link_path(destination)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_reproducibility_link_path(destination)
    temp = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    temp_identity = _owned_directory_identity(temp)
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
            _reject_reproducibility_link_path(source)
            if (
                not source.is_file()
                or source.is_symlink()
                or getattr(source, "is_junction", lambda: False)()
            ):
                raise BundleError("candidate manifest path must be a real file")
            candidate_raw, _ = _read_inventory_file(source)
            try:
                candidate_text = candidate_raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BundleError("candidate manifest is not UTF-8") from exc
            candidate = _parse_bounded_json(candidate_text, "candidate manifest")
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
        (temp / "README.md").write_bytes(_LEGACY_README)
        (temp / "reproduce.sh").write_bytes(_LEGACY_REPRODUCE_SCRIPT)
        os.chmod(temp / "reproduce.sh", 0o755)
        required = REQUIRED + (("candidate-manifest.json",) if metadata["family"] == "qa" else ())
        _write_json(
            temp / "bundle-manifest.json",
            {"files": {name: _digest(temp / name) for name in required}, "version": 1},
        )
        _reject_reproducibility_link_path(destination)
        _publish_directory_noreplace(temp, destination)
    except BaseException:
        _remove_owned_directory(temp, temp_identity)
        raise


def verify_bundle(bundle: Path | str) -> dict[str, Any]:
    """Verify a bundle through a fail-closed public exception boundary."""
    try:
        return _verify_bundle(bundle)
    except BundleError:
        raise
    except (OSError, UnicodeError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise BundleError("bundle verification failed safely") from exc


def _verify_bundle(bundle: Path | str) -> dict[str, Any]:
    root = Path(bundle)
    repro = root / REPRODUCIBILITY_MANIFEST_NAME
    if repro.exists() or repro.is_symlink():
        return _verify_reproducibility_bundle(root)
    _reject_reproducibility_link_path(root)
    if (
        not root.is_dir()
        or root.is_symlink()
        or getattr(root, "is_junction", lambda: False)()
    ):
        raise BundleError("bundle must be a real directory, not a link")
    root_identity = _owned_directory_identity(root)
    entries: list[Path] = []
    for entry_number, entry in enumerate(root.iterdir(), start=1):
        if entry_number > _MAX_REPRO_FILES:
            raise BundleError("bundle exceeds the closed file-count bound")
        entries.append(entry)
    actual = {entry.name for entry in entries}
    payload_files = REQUIRED + (("candidate-manifest.json",) if "candidate-manifest.json" in actual else ())
    expected = {*payload_files, "bundle-manifest.json"}
    if actual != expected:
        raise BundleError("inventory mismatch")
    payloads: dict[str, bytes] = {}
    total_size = 0
    for entry in entries:
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            raise BundleError(f"links and non-files are forbidden: {entry.name}")
        if entry.resolve().parent != root.resolve():
            raise BundleError(f"path escapes bundle: {entry.name}")
        payload, entry_size = _read_inventory_file(entry)
        total_size += entry_size
        if total_size > _MAX_REPRO_BUNDLE_BYTES:
            raise BundleError("bundle exceeds the closed aggregate size bound")
        payloads[entry.name] = payload
    raw = b"".join(payloads[name] for name in sorted(actual))
    if SECRET.search(raw.decode("utf-8", errors="replace")):
        raise BundleError("secret-like material detected")
    _validate_legacy_canonical_bytes(payloads)
    manifest = _load_inventory_json(payloads, "bundle-manifest.json")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"files", "version"}
        or type(manifest.get("version")) is not int
        or manifest["version"] != 1
        or not isinstance(manifest.get("files"), dict)
        or any(
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in manifest["files"].values()
        )
    ):
        raise BundleError("invalid legacy bundle manifest schema")
    if set(manifest.get("files", {})) != set(payload_files):
        raise BundleError("manifest inventory mismatch")
    for name, expected_digest in manifest["files"].items():
        if hashlib.sha256(payloads[name]).hexdigest() != expected_digest:
            raise BundleError(f"digest mismatch: {name}")
    benchmark, config, measured, build = (
        _load_inventory_json(payloads, "benchmark.json"),
        _load_inventory_json(payloads, "config.json"),
        _load_inventory_json(payloads, "metrics.json"),
        _load_inventory_json(payloads, "build.json"),
    )
    judge = _load_inventory_json(payloads, "judge.json")
    try:
        trace_text = payloads["traces.jsonl"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("invalid UTF-8 in traces.jsonl") from exc
    traces = [_parse_bounded_json(line, "traces.jsonl") for line in trace_text.splitlines()]
    if any(
        not isinstance(value, dict)
        for value in (benchmark, config, measured, build, judge, *traces)
    ):
        raise BundleError("legacy bundle JSON artifacts must be objects")
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
    if not isinstance(metadata, dict):
        raise BundleError("legacy benchmark metadata must be an object")
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
    expected_build_keys = {"environment_contract", "system_seam", "version"}
    if family == "qa":
        expected_build_keys.add("candidate_git_sha")
    if (
        set(build) != expected_build_keys
        or build.get("environment_contract") != "uv run --locked"
        or type(build.get("version")) is not int
        or build["version"] != 1
    ):
        raise BundleError("invalid legacy build contract")
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
        custody = metadata.get("reader_custody")
        expected_reader = (
            custody.get("reader", {}).get("name")
            if isinstance(custody, dict)
            else None
        )
        if judge != {
            "custody": custody,
            "judge": "benchmark-owned-qa-em-f1-v1",
            "reader": expected_reader,
        }:
            raise BundleError("invalid legacy QA judge contract")
        _verify_qa_custody(
            metadata,
            judge,
            benchmark.get("data"),
            traces,
            payloads["candidate-manifest.json"],
            measured,
            build,
        )
    elif judge != {
        "judge": None,
        "reader": None,
        "reason": f"{family} family",
    }:
        raise BundleError("invalid legacy deterministic judge contract")
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
    _assert_inventory_snapshot(root, payloads)
    _assert_directory_identity(root, root_identity, "bundle")
    return {"family": family, "suite": metadata.get("suite"), "valid": True}


def _validate_legacy_canonical_bytes(payloads: dict[str, bytes]) -> None:
    """Require the exact deterministic JSON encoding emitted by result-v1."""
    if payloads.get("README.md") != _LEGACY_README:
        raise BundleError("legacy bundle README bytes do not match result-v1")
    if payloads.get("reproduce.sh") != _LEGACY_REPRODUCE_SCRIPT:
        raise BundleError("legacy reproduction script bytes do not match result-v1")
    for name, payload in payloads.items():
        if not (name.endswith(".json") or name.endswith(".jsonl")):
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BundleError(f"invalid UTF-8 in {name}") from exc
        if name.endswith(".jsonl"):
            values = [_parse_bounded_json(line, name) for line in text.splitlines()]
            canonical = b"".join(_canonical(value) for value in values)
        else:
            canonical = _canonical(_parse_bounded_json(text, name))
        if payload != canonical:
            raise BundleError(f"non-canonical JSON bytes in {name}")


def _assert_inventory_snapshot(root: Path, payloads: dict[str, bytes]) -> None:
    """Require the closed bundle inventory to still match its captured bytes."""
    names: set[str] = set()
    total_size = 0
    for entry_number, entry in enumerate(root.iterdir(), start=1):
        if entry_number > _MAX_REPRO_FILES:
            raise BundleError("bundle changed after verification")
        names.add(entry.name)
    if names != set(payloads):
        raise BundleError("bundle changed after verification")
    for name in sorted(names):
        current, size = _read_inventory_file(root / name)
        total_size += size
        if total_size > _MAX_REPRO_BUNDLE_BYTES or current != payloads[name]:
            raise BundleError("bundle changed after verification")


def reproduce_bundle(source: Path | str, destination: Path | str) -> dict[str, Any]:
    source_root = Path(source)
    repro = source_root / REPRODUCIBILITY_MANIFEST_NAME
    if repro.exists() or repro.is_symlink():
        return _reproduce_reproducibility_bundle(source_root, Path(destination))
    from eval.public.runner import run_public_suite

    destination = _absolute_normalized_path(Path(destination))
    _reject_reproducibility_link_path(destination)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_reproducibility_link_path(destination)
    snapshot = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-source-", dir=destination.parent)
    )
    snapshot_identity = _owned_directory_identity(snapshot)
    destination_identity: tuple[int, int] | None = None
    try:
        _snapshot_legacy_bundle(source_root, snapshot)
        verify_bundle(snapshot)
        benchmark_payload, _ = _read_inventory_file(snapshot / "benchmark.json")
        custody = _load_inventory_json(
            {"benchmark.json": benchmark_payload}, "benchmark.json"
        )
        result = run_public_suite(
            custody["metadata"]["suite"],
            destination,
            benchmark_override=custody["data"],
            candidate_manifest_path=(snapshot / "candidate-manifest.json")
            if custody["metadata"]["family"] == "qa"
            else None,
        )
        destination_identity = _owned_directory_identity(destination)
        verify_bundle(destination)
        for name in _manifest_files(snapshot):
            expected, _ = _read_inventory_file(snapshot / name)
            reproduced, _ = _read_inventory_file(destination / name)
            if expected != reproduced:
                raise BundleError(f"reproduction mismatch: {name}")
        return result
    except BaseException:
        if destination_identity is not None:
            _remove_owned_directory(destination, destination_identity)
        raise
    finally:
        _remove_owned_directory(snapshot, snapshot_identity)


def _snapshot_legacy_bundle(source: Path, snapshot: Path) -> None:
    """Copy one closed legacy bundle into a private stable-byte snapshot."""
    _reject_reproducibility_link_path(source)
    if (
        not source.is_dir()
        or source.is_symlink()
        or getattr(source, "is_junction", lambda: False)()
    ):
        raise BundleError("bundle must be a real directory, not a link")
    source_identity = _owned_directory_identity(source)
    total_size = 0
    names: set[str] = set()
    for entry_number, entry in enumerate(source.iterdir(), start=1):
        if entry_number > _MAX_REPRO_FILES:
            raise BundleError("bundle exceeds the closed file-count bound")
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            raise BundleError(f"links and non-files are forbidden: {entry.name}")
        if entry.resolve().parent != source.resolve():
            raise BundleError(f"path escapes bundle: {entry.name}")
        payload, entry_size = _read_inventory_file(entry)
        total_size += entry_size
        if total_size > _MAX_REPRO_BUNDLE_BYTES:
            raise BundleError("bundle exceeds the closed aggregate size bound")
        (snapshot / entry.name).write_bytes(payload)
        names.add(entry.name)
    if names != {entry.name for entry in source.iterdir()}:
        raise BundleError("bundle inventory changed while snapshotting")
    _assert_directory_identity(source, source_identity, "bundle")


def write_report(
    source: Path | str,
    reproduced: Path | str,
    report_output: Path | str,
    report_note: Path | str,
) -> dict[str, Any]:
    """Write a report from private snapshots of two matching legacy bundles."""
    source_display = _absolute_normalized_path(Path(source))
    reproduced_display = _absolute_normalized_path(Path(reproduced))
    source_snapshot = Path(tempfile.mkdtemp(prefix="mnemo-report-source-"))
    source_identity = _owned_directory_identity(source_snapshot)
    try:
        reproduced_snapshot = Path(
            tempfile.mkdtemp(prefix="mnemo-report-reproduced-")
        )
        reproduced_identity = _owned_directory_identity(reproduced_snapshot)
    except BaseException:
        _remove_owned_directory(source_snapshot, source_identity)
        raise
    try:
        _snapshot_legacy_bundle(source_display, source_snapshot)
        _snapshot_legacy_bundle(reproduced_display, reproduced_snapshot)
        return _write_report_from_snapshots(
            source_snapshot,
            reproduced_snapshot,
            report_output,
            report_note,
            source_display=source_display,
            reproduced_display=reproduced_display,
        )
    finally:
        _remove_owned_directory(reproduced_snapshot, reproduced_identity)
        _remove_owned_directory(source_snapshot, source_identity)


def _write_report_from_snapshots(
    source_root: Path,
    reproduced_root: Path,
    report_output: Path | str,
    report_note: Path | str,
    *,
    source_display: Path,
    reproduced_display: Path,
) -> dict[str, Any]:
    """Write one report from already private bundle snapshots."""
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
    output = _absolute_normalized_path(Path(report_output))
    note = _absolute_normalized_path(Path(report_note))
    _reject_reproducibility_link_path(output)
    _reject_reproducibility_link_path(note)
    if output.exists() or note.exists():
        raise FileExistsError("refusing to overwrite report output or note")
    git_sha = _git_sha()
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence = _report_evidence(
        source_root,
        reproduced_root,
        source_display=source_display,
        reproduced_display=reproduced_display,
    )
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
            str(_absolute_normalized_path(source_display)),
            "--reproduced-bundle",
            str(_absolute_normalized_path(reproduced_display)),
            "--report-output",
            str(_absolute_normalized_path(output)),
            "--report-note",
            str(_absolute_normalized_path(note)),
        ],
        "publication": {
            "independent_external_reproduction": False,
            "pbpp_headline_eligible": False,
            "publishable": False,
        },
        "reproduced_bundle": str(_absolute_normalized_path(reproduced_display)),
        "source_bundle": str(_absolute_normalized_path(source_display)),
        "suite": source_result["suite"],
        "version": 1,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    note.parent.mkdir(parents=True, exist_ok=True)
    _reject_reproducibility_link_path(output)
    _reject_reproducibility_link_path(note)
    output_identity = _atomic_write_noreplace(output, _canonical(report))
    report_payload, _ = _read_inventory_file(output)
    report_digest = hashlib.sha256(report_payload).hexdigest()
    markdown = _render_report_note(report, report_digest)
    try:
        _atomic_write_noreplace(note, markdown)
    except BaseException:
        _remove_owned_file(output, output_identity)
        raise
    return {
        "report": str(_absolute_normalized_path(output)),
        "report_note": str(_absolute_normalized_path(note)),
        "sha256": report_digest,
        "valid": True,
    }


def verify_report(report_path: Path | str, report_note: Path | str) -> dict[str, Any]:
    """Verify report custody through a fail-closed public exception boundary."""
    try:
        return _verify_report(report_path, report_note)
    except BundleError:
        raise
    except (OSError, UnicodeError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise BundleError("report verification failed safely") from exc


def _verify_report(
    report_path: Path | str,
    report_note: Path | str,
    *,
    source_snapshot: Path | None = None,
    reproduced_snapshot: Path | None = None,
    expected_report_payload: bytes | None = None,
    expected_note_bytes: bytes | None = None,
) -> dict[str, Any]:
    report_file, note_file = Path(report_path), Path(report_note)
    for path in (report_file, note_file):
        _reject_reproducibility_link_path(path)
        if (
            path.is_symlink()
            or getattr(path, "is_junction", lambda: False)()
            or not path.is_file()
        ):
            raise BundleError("report and report note must be real files, not links")
    report_payload, _ = _read_inventory_file(report_file)
    note_bytes, _ = _read_inventory_file(note_file)
    if (
        expected_report_payload is not None
        and report_payload != expected_report_payload
    ) or (expected_note_bytes is not None and note_bytes != expected_note_bytes):
        raise BundleError("report artifacts changed while snapshotting bundles")
    try:
        report_text = report_payload.decode("utf-8")
        note = note_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("report and report note must be UTF-8") from exc
    report = _parse_bounded_json(report_text, report_file.name)
    if report_payload != _canonical(report):
        raise BundleError("report bytes must be canonical")
    if (
        not isinstance(report, dict)
        or set(report)
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
        or type(report["version"]) is not int
        or report["version"] != 1
        or not isinstance(report["bindings"], dict)
        or not isinstance(report["command"], list)
        or not isinstance(report["evidence"], dict)
        or not isinstance(report["publication"], dict)
        or not isinstance(report["suite"], str)
        or not report["suite"].strip()
        or any(
            not isinstance(report[field], str)
            or not report[field].strip()
            or "\x00" in report[field]
            for field in (
                "generated_at",
                "git_sha",
                "reproduced_bundle",
                "source_bundle",
            )
        )
    ):
        raise BundleError("invalid report schema")
    if len(report["git_sha"]) != 40 or set(report["git_sha"]) - set(
        "0123456789abcdef"
    ):
        raise BundleError("invalid report git SHA")
    source_display, reproduced_display = (
        Path(report["source_bundle"]),
        Path(report["reproduced_bundle"]),
    )
    if source_snapshot is None or reproduced_snapshot is None:
        captured_source = Path(tempfile.mkdtemp(prefix="mnemo-verify-source-"))
        source_identity = _owned_directory_identity(captured_source)
        try:
            captured_reproduced = Path(
                tempfile.mkdtemp(prefix="mnemo-verify-reproduced-")
            )
            reproduced_identity = _owned_directory_identity(captured_reproduced)
        except BaseException:
            _remove_owned_directory(captured_source, source_identity)
            raise
        try:
            _snapshot_legacy_bundle(source_display, captured_source)
            _snapshot_legacy_bundle(reproduced_display, captured_reproduced)
            return _verify_report(
                report_file,
                note_file,
                source_snapshot=captured_source,
                reproduced_snapshot=captured_reproduced,
                expected_report_payload=report_payload,
                expected_note_bytes=note_bytes,
            )
        finally:
            _remove_owned_directory(captured_reproduced, reproduced_identity)
            _remove_owned_directory(captured_source, source_identity)
    source, reproduced = source_snapshot, reproduced_snapshot
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
        str(_absolute_normalized_path(source_display)),
        "--reproduced-bundle",
        str(_absolute_normalized_path(reproduced_display)),
        "--report-output",
        str(_absolute_normalized_path(report_file)),
        "--report-note",
        str(_absolute_normalized_path(note_file)),
    ]
    if report.get("command") != expected_command:
        raise BundleError("report command provenance mismatch")
    if report.get("evidence") != _report_evidence(
        source,
        reproduced,
        source_display=source_display,
        reproduced_display=reproduced_display,
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
    report_digest = hashlib.sha256(report_payload).hexdigest()
    if note_bytes != _render_report_note(report, report_digest):
        raise BundleError("report note binding is not the exact canonical projection")
    for value in (
        report_digest,
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
        "report": str(_absolute_normalized_path(report_file)),
        "report_note": str(_absolute_normalized_path(note_file)),
        "sha256": report_digest,
        "valid": True,
    }


def _report_evidence(
    source: Path,
    reproduced: Path,
    *,
    source_display: Path | None = None,
    reproduced_display: Path | None = None,
) -> dict[str, Any]:
    source_display = source if source_display is None else source_display
    reproduced_display = reproduced if reproduced_display is None else reproduced_display
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
            "source_bundle": str(_absolute_normalized_path(source_display)),
            "system_seam": build.get("system_seam"),
        },
        "reproduction": {
            "matched_files": list(_manifest_files(source)),
            "reproduced_bundle": str(_absolute_normalized_path(reproduced_display)),
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
    candidate_payload: bytes,
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
    try:
        candidate_text = candidate_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("invalid UTF-8 in candidate-manifest.json") from exc
    candidate = _parse_bounded_json(candidate_text, "candidate-manifest.json")
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
    if hashlib.sha256(candidate_payload).hexdigest() != custody["candidate_manifest_sha256"]:
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


def _reject_reproducibility_link_path(path: Path) -> None:
    """Reject symlinks or junctions in every existing path component."""
    absolute = _absolute_normalized_path(path)
    current = Path(absolute.anchor)
    parts = absolute.parts[1:] if absolute.anchor else absolute.parts
    try:
        for part in parts:
            current /= part
            if current.is_symlink() or getattr(
                current, "is_junction", lambda: False
            )():
                raise BundleError(
                    "reproducibility paths must not contain links or junctions"
                )
    except BundleError:
        raise
    except OSError as exc:
        raise BundleError("reproducibility path components cannot be inspected") from exc


def _absolute_normalized_path(path: Path) -> Path:
    """Normalize dot segments without resolving symlinks or junctions."""
    return Path(os.path.abspath(os.fspath(path)))


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


def _load_inventory_json(payloads: dict[str, bytes], name: str) -> Any:
    """Parse JSON from the exact bytes authenticated by the bundle inventory."""
    try:
        raw = payloads[name].decode("utf-8")
    except KeyError as exc:
        raise BundleError(f"missing {name}") from exc
    except UnicodeDecodeError as exc:
        raise BundleError(f"invalid UTF-8 in {name}") from exc
    return _parse_bounded_json(raw, name)


def _parse_bounded_json(raw: str, label: str) -> Any:
    value = _parse_json(raw, label)
    _json_depth(value)
    _reject_decoded_secrets(value)
    return value


def _reject_decoded_secrets(value: object) -> None:
    """Reject secret patterns after JSON escape decoding, including keys."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str) and SECRET.search(current):
            raise BundleError("secret-like material detected in decoded artifact")
        if isinstance(current, dict):
            key_type = current.get("kty")
            if isinstance(key_type, str) and (
                (key_type in {"EC", "OKP", "RSA"} and "d" in current)
                or (key_type == "oct" and "k" in current)
            ):
                raise BundleError("private JWK material detected in decoded artifact")
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


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


def _atomic_write_noreplace(path: Path, payload: bytes) -> tuple[int, int]:
    """Atomically publish one private temporary file without replacing a path."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise BundleError("private report path is not a regular file")
            identity = metadata.st_dev, metadata.st_ino
        if os.name == "nt":
            Path(temporary).rename(path)
        else:
            os.link(temporary, path)
            Path(temporary).unlink()
        return identity
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
def _remove_owned_file(path: Path, identity: tuple[int, int]) -> None:
    """Remove a report only while its original inode is still named."""
    try:
        metadata = path.stat(follow_symlinks=False)
    except (FileNotFoundError, OSError):
        return
    if (
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and (metadata.st_dev, metadata.st_ino) == identity
    ):
        path.unlink(missing_ok=True)


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
