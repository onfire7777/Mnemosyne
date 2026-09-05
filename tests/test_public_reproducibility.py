from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import json
import os
import platform
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eval.public import bundle as public_bundle
from eval.public.bundle import BundleError
from leaderboard.ledger import append_entry
from eval.public.runner import run_public_suite
from tests.test_leaderboard_result_contract import (
    _v2_development_record,
    _v2_official_record,
    _v2_successor_record,
)
from tests.test_public_eval import _canonical_replay_payload


DIGEST = "sha256:" + "a" * 64
COMMAND = [
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
]
SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "eval"
    / "public"
    / "schema"
    / "reproducibility-bundle-v1.schema.json"
)
PLATFORM = f"{sys.platform}-{platform.machine().lower()}"
RUNTIME = f"cpython-{sys.version_info.major}.{sys.version_info.minor}"
GIT_SHA = public_bundle._git_sha()


def _validate(manifest: object) -> dict[str, object]:
    validator = getattr(public_bundle, "validate_reproducibility_manifest", None)
    assert callable(validator), "missing reproducibility manifest version dispatch"
    return validator(manifest)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _media_type(name: str) -> str:
    if name.endswith(".json"):
        return "application/json"
    if name.endswith(".jsonl"):
        return "application/x-ndjson"
    if name.endswith(".pem"):
        return "application/x-pem-file"
    if name == "README.md":
        return "text/markdown"
    if name == "reproduce.sh":
        return "text/x-shellscript"
    return "text/plain"


def _write_reproducibility_bundle(root: Path) -> dict[str, object]:
    run_public_suite("smoke", root)
    payloads = {entry.name: entry.read_bytes() for entry in root.iterdir()}
    locked_dependencies = public_bundle._locked_dependencies(Path("uv.lock"))
    payloads.update(
        {
            "environment.json": _canonical(
                {
                    "platform": PLATFORM,
                    "runtime": RUNTIME,
                    "dependencies": locked_dependencies,
                    "locale": "C",
                    "timezone": "UTC",
                    "environment": {"PYTHONHASHSEED": "0"},
                }
            ),
            "uv.lock": Path("uv.lock").read_bytes(),
            "fixture-manifest.json": _canonical({"kind": "synthetic"}),
            "generator-manifest.json": _canonical({"seeded": True}),
            "adapter-manifest.json": _canonical({"adapter": "smoke"}),
            "scorer-manifest.json": _canonical({"profile": "smoke-hit-at-k-v1"}),
            "baseline-manifest.json": _canonical({"baseline": "none"}),
            "prompt-manifest.json": _canonical({"prompt": "none"}),
        }
    )
    record = _v2_development_record()
    benchmark_manifest = json.loads(payloads["benchmark.json"])
    benchmark_metadata = benchmark_manifest["metadata"]
    record["run_commit"] = GIT_SHA
    record["benchmark"] = benchmark_metadata["suite"]
    record["benchmark_version"] = benchmark_metadata["revision"]
    record["build_fingerprint"] = _digest(payloads["build.json"])
    record["config_digest"] = _digest(payloads["config.json"])
    record["bundle_digest"] = _digest(payloads["bundle-manifest.json"])
    record["trace_index_digest"] = _digest(payloads["traces.jsonl"])
    record["metrics"] = [
        {
            "name": "hit_at_k",
            "family": "retrieval",
            "value": 1.0,
            "unit": "ratio",
            "confidence_interval": {"low": 0.3424, "high": 1.0},
        }
    ]
    identity = record["identity"]
    identity.update(  # type: ignore[union-attr]
        {
            "adapter_id": benchmark_metadata["adapter"],
            "benchmark_id": record["benchmark"],
            "benchmark_version": record["benchmark_version"],
            "dataset_split_digest": _digest(payloads["benchmark.json"]),
            "seed": 20260728,
        }
    )
    record["run_profile"] = {
        "profile_id": "L16-DEV",
        "seeds": [20260728],
        "retries": 0,
        "aborts": 0,
    }
    record["operator_entry"] = {
        "operator": "development-test",
        "disclosed": True,
    }
    record["custody"] = "development-public"
    record["signer_role"] = "operator"
    payloads["result.json"] = _canonical(record)
    replay = _canonical_replay_payload("wmbs-m01-development")
    replay["manifests"] = {  # type: ignore[index]
        "bundle_manifest_sha256": _digest(payloads["bundle-manifest.json"])[7:],
        "fixture_manifest_sha256": _digest(payloads["fixture-manifest.json"])[7:],
        "generator_manifest_sha256": _digest(payloads["generator-manifest.json"])[7:],
    }
    replay["fixture"] = (  # type: ignore[index]
        "wmbs-m01-development@" + _digest(payloads["fixture-manifest.json"])
    )
    replay["build"] = {  # type: ignore[index]
        "candidate_git_sha": GIT_SHA,
        "system_seam": json.loads(payloads["build.json"])["system_seam"],
    }
    payloads["canonical-replay.json"] = _canonical(replay)
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)

    private_key = Ed25519PrivateKey.generate()
    private_path = root.parent / "ledger-private.pem"
    public_path = root / "ledger-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    ledger_path = root / "ledger.jsonl"
    ledger_entry = append_entry(
        ledger_path,
        private_path,
        entry_id="repro-entry-1",
        timestamp="2026-09-05T12:00:00Z",
        entrant_id="mnemosyne-development",
        status="succeeded",
        run_id="repro-run-1",
        result=record,
        roster={"mnemosyne-development"},
    )
    for name in (
        "ledger.jsonl",
        "ledger.jsonl.head.json",
        "ledger.jsonl.lock",
        "ledger-public.pem",
    ):
        payloads[name] = (root / name).read_bytes()

    manifest = _manifest()
    manifest["run"]["dependencies"] = locked_dependencies  # type: ignore[index]
    manifest["inputs"] = {
        "benchmark_manifest_digest": _digest(payloads["benchmark.json"]),
        "dataset_manifest_digest": _digest(payloads["benchmark.json"]),
        "fixture_manifest_digest": _digest(payloads["fixture-manifest.json"]),
        "generator_manifest_digest": _digest(payloads["generator-manifest.json"]),
        "adapter_manifest_digest": _digest(payloads["adapter-manifest.json"]),
        "scorer_manifest_digest": _digest(payloads["scorer-manifest.json"]),
        "baseline_manifest_digest": _digest(payloads["baseline-manifest.json"]),
        "judge_manifest_digest": _digest(payloads["judge.json"]),
        "prompt_manifest_digest": _digest(payloads["prompt-manifest.json"]),
    }
    manifest["result_ref"] = {
        "record_id": record["record_id"],
        "result_digest": _digest(payloads["result.json"]),
        "ledger_entry_digest": ledger_entry["entry_digest"],
        "track_kind": record["track_kind"],
        "lineage": record["lineage"],
    }
    artifacts = manifest["artifacts"]  # type: ignore[assignment]
    artifacts.update(  # type: ignore[union-attr]
        {
            "build_fingerprint": _digest(payloads["build.json"]),
            "config_digest": _digest(payloads["config.json"]),
            "bundle_digest": _digest(payloads["bundle-manifest.json"]),
            "trace_index_digest": _digest(payloads["traces.jsonl"]),
            "canonical_replay_digest": "sha256:"
            + public_bundle.canonical_replay_digest(replay),
            "environment_digest": _digest(payloads["environment.json"]),
            "lockfile_digest": _digest(payloads["uv.lock"]),
            "files": [
                {
                    "path": name,
                    "size": len(payload),
                    "media_type": _media_type(name),
                    "canonicalization": "exact-bytes",
                    "digest": _digest(payload),
                }
                for name, payload in sorted(payloads.items())
            ],
        }
    )
    manifest["metrics"] = [
        {
            "family": "retrieval",
            "name": "hit_at_k",
            "version": "1",
            "value": 1.0,
            "unit": "ratio",
            "numerator": 2,
            "denominator": 2,
            "sample_count": 2,
            "interval": {
                "method": "wilson",
                "confidence_level": 0.95,
                "low": 0.3424,
                "high": 1.0,
                "parameters": {},
            },
            "exclusions": [],
            "outcomes": {
                "missing": 0,
                "unsupported": 0,
                "failed": 0,
                "aborted": 0,
                "not_measured": 0,
            },
        }
    ]
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))
    return manifest


def _refresh_owned_file(root: Path, name: str) -> None:
    manifest_path = root / "reproducibility-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = (root / name).read_bytes()
    entry = next(
        item for item in manifest["artifacts"]["files"] if item["path"] == name
    )
    entry["size"] = len(payload)
    entry["digest"] = _digest(payload)
    manifest_path.write_bytes(_canonical(manifest))


def _clear_credential_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if public_bundle._credential_environment_name(
            name
        ) or public_bundle._undeclared_influential_environment_name(
            name, {"PYTHONHASHSEED"}
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("TZ", "UTC")


def _manifest(*, track_kind: str = "DEVELOPMENT") -> dict[str, object]:
    lineage: dict[str, object]
    if track_kind == "OFFICIAL-UPSTREAM":
        lineage = copy.deepcopy(_v2_official_record()["lineage"])  # type: ignore[assignment]
    elif track_kind == "ENHANCED-SUCCESSOR":
        lineage = copy.deepcopy(_v2_successor_record()["lineage"])  # type: ignore[assignment]
    else:
        lineage = {}
    return {
        "schema_version": "mnemosyne.reproducibility-bundle/v1",
        "result_ref": {
            "record_id": "development-result-1",
            "result_digest": DIGEST,
            "ledger_entry_digest": DIGEST,
            "track_kind": track_kind,
            "lineage": lineage,
        },
        "inputs": {
            "benchmark_manifest_digest": DIGEST,
            "dataset_manifest_digest": DIGEST,
            "fixture_manifest_digest": DIGEST,
            "generator_manifest_digest": DIGEST,
            "adapter_manifest_digest": DIGEST,
            "scorer_manifest_digest": DIGEST,
            "baseline_manifest_digest": DIGEST,
            "judge_manifest_digest": DIGEST,
            "prompt_manifest_digest": DIGEST,
        },
        "artifacts": {
            "build_fingerprint": DIGEST,
            "config_digest": DIGEST,
            "bundle_digest": DIGEST,
            "trace_index_digest": DIGEST,
            "canonical_replay_digest": DIGEST,
            "environment_digest": DIGEST,
            "lockfile_digest": DIGEST,
            "files": [
                {
                    "path": "traces.jsonl",
                    "size": 3,
                    "media_type": "application/x-ndjson",
                    "canonicalization": "exact-bytes",
                    "digest": DIGEST,
                }
            ],
        },
        "run": {
            "candidate_git_sha": GIT_SHA,
            "dirty": False,
            "platform": PLATFORM,
            "runtime": RUNTIME,
            "dependencies": ["mnemosyne==0.1.0"],
            "locale": "C",
            "timezone": "UTC",
            "environment": {"PYTHONHASHSEED": "0"},
            "seed_records": [20260728],
            "retries": 0,
            "aborts": 0,
        },
        "metrics": [
            {
                "family": "retrieval",
                "name": "recall_at_k",
                "version": "1",
                "value": 1.0,
                "unit": "ratio",
                "numerator": 1,
                "denominator": 1,
                "sample_count": 1,
                "interval": {
                    "method": "wilson",
                    "confidence_level": 0.95,
                    "low": 0.2,
                    "high": 1.0,
                    "parameters": {"continuity_correction": False},
                },
                "exclusions": [],
                "outcomes": {
                    "missing": 0,
                    "unsupported": 0,
                    "failed": 0,
                    "aborted": 0,
                    "not_measured": 0,
                },
            }
        ],
        "disclosures": {
            "software_license": "Apache-2.0",
            "data_license": "synthetic-test-data",
            "source_revision": GIT_SHA,
            "redistribution_permitted": True,
            "pii_present": False,
            "consent_documented": True,
            "takedown_process": "security@example.invalid",
            "custody_class": "development-public",
            "operator_identity": "development-test",
            "operator_role": "test-operator",
            "signer_role": "operator",
            "disclosure_state": "COMPLETE",
            "independent_reproduction": None,
        },
        "reproduction": {"argv": COMMAND, "network": "forbidden"},
    }


def test_schema_is_valid_closed_draft_2020_12() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("reproducibility-bundle-v1.schema.json")

    authored_objects: list[dict[str, object]] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" and "properties" in value:
                authored_objects.append(value)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(schema)
    assert authored_objects
    assert all(item.get("additionalProperties") is False for item in authored_objects)
    result_ref = schema["properties"]["result_ref"]
    lineage_conditions = {
        condition["if"]["properties"]["track_kind"]["const"]
        for condition in result_ref["allOf"]
    }
    assert lineage_conditions == {
        "DEVELOPMENT",
        "OFFICIAL-UPSTREAM",
        "ENHANCED-SUCCESSOR",
    }


def test_accepts_closed_development_manifest() -> None:
    assert _validate(_manifest())["track_kind"] == "DEVELOPMENT"


@pytest.mark.parametrize("track_kind", ["OFFICIAL-UPSTREAM", "ENHANCED-SUCCESSOR"])
def test_accepts_each_lineage_without_blending(track_kind: str) -> None:
    manifest = _manifest(track_kind=track_kind)
    authoritative = (
        _v2_official_record()
        if track_kind == "OFFICIAL-UPSTREAM"
        else _v2_successor_record()
    )
    assert manifest["result_ref"]["lineage"] == authoritative["lineage"]  # type: ignore[index]
    assert _validate(manifest)["track_kind"] == track_kind


def test_rejects_unknown_or_missing_top_level_fields() -> None:
    unknown = _manifest()
    unknown["headline_eligible"] = True
    with pytest.raises(BundleError, match="unknown field"):
        _validate(unknown)

    missing = _manifest()
    del missing["disclosures"]
    with pytest.raises(BundleError, match="missing field"):
        _validate(missing)


@pytest.mark.parametrize(
    "argv",
    [
        COMMAND[:-1],
        [*COMMAND[:-1], "elsewhere"],
        ["sh", "-c", "uv run --locked mneme eval-public"],
    ],
)
def test_rejects_any_command_other_than_exact_repository_root_argv(
    argv: list[str],
) -> None:
    manifest = _manifest()
    manifest["reproduction"]["argv"] = argv  # type: ignore[index]
    with pytest.raises(BundleError, match="reproduction command"):
        _validate(manifest)


def test_development_track_cannot_carry_official_or_successor_lineage() -> None:
    manifest = _manifest()
    manifest["result_ref"]["lineage"] = {  # type: ignore[index]
        "fidelity_manifest_digest": DIGEST
    }
    with pytest.raises(BundleError, match="development lineage"):
        _validate(manifest)


def test_rejects_non_finite_metric_and_secret_environment_value() -> None:
    non_finite = _manifest()
    non_finite["metrics"][0]["value"] = float("nan")  # type: ignore[index]
    with pytest.raises(BundleError, match="finite"):
        _validate(non_finite)

    secret = copy.deepcopy(_manifest())
    secret["run"]["environment"]["TOKEN"] = "ghp_" + "x" * 32  # type: ignore[index]
    with pytest.raises(BundleError, match="secret"):
        _validate(secret)


@pytest.mark.parametrize(
    ("field", "credential"),
    [
        ("operator_identity", "Authorization: Bearer " + "a" * 32),
        ("takedown_process", "postgresql://public:supersecret@database.example/db"),
    ],
)
def test_manifest_rejects_credentials_outside_environment(
    field: str, credential: str
) -> None:
    manifest = _manifest()
    manifest["disclosures"][field] = credential  # type: ignore[index]

    with pytest.raises(BundleError, match="secret-like material detected in manifest"):
        _validate(manifest)


def test_manifest_rejects_credential_in_parameter_key() -> None:
    manifest = _manifest()
    manifest["metrics"][0]["interval"]["parameters"] = {  # type: ignore[index]
        "github_pat_" + "a" * 24: "redacted"
    }

    with pytest.raises(BundleError, match="secret-like material detected in manifest"):
        _validate(manifest)


def test_manifest_structural_budget_counts_values_without_double_counting_keys() -> None:
    public_bundle._repro_finite({f"field_{index}": index for index in range(60_000)})


@pytest.mark.parametrize(
    "name",
    [
        "PYTHONPATH",
        "UV_INDEX_URL",
        "HTTPS_PROXY",
        "GIT_DIR",
        "OPENAI_API_KEY",
        "DATABASE_URL",
        "SSH_AUTH_SOCK",
    ],
)
def test_manifest_cannot_allowlist_execution_influences(name: str) -> None:
    manifest = _manifest()
    manifest["run"]["environment"][name] = "attacker-controlled"  # type: ignore[index]

    with pytest.raises(BundleError, match="environment names are forbidden"):
        _validate(manifest)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    property_rules = schema["properties"]["run"]["properties"]["environment"][  # type: ignore[index]
        "propertyNames"
    ]["allOf"]
    denial_patterns = [rule["not"]["pattern"] for rule in property_rules if "not" in rule]
    assert any(re.search(pattern, name) for pattern in denial_patterns)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("value", "1.0", "metric value"),
        ("numerator", True, "metric numerator"),
        ("denominator", "2", "metric denominator"),
    ],
)
def test_runtime_validator_enforces_metric_number_types(
    field: str, value: object, message: str
) -> None:
    manifest = _manifest()
    manifest["metrics"][0][field] = value  # type: ignore[index]
    with pytest.raises(BundleError, match=message):
        _validate(manifest)


def test_metric_numerator_and_denominator_are_optional_only_as_a_pair() -> None:
    sample_count_only = _manifest()
    sample_count_only["metrics"][0]["numerator"] = None  # type: ignore[index]
    sample_count_only["metrics"][0]["denominator"] = None  # type: ignore[index]
    assert _validate(sample_count_only)["valid"] is True

    unpaired = _manifest()
    unpaired["metrics"][0]["numerator"] = None  # type: ignore[index]
    with pytest.raises(BundleError, match="must be paired"):
        _validate(unpaired)


def test_runtime_validator_enforces_metric_parameter_and_exclusion_bounds() -> None:
    invalid_parameter = _manifest()
    invalid_parameter["metrics"][0]["interval"]["parameters"] = {  # type: ignore[index]
        "nested": {"not": "a scalar"}
    }
    with pytest.raises(BundleError, match="interval parameters"):
        _validate(invalid_parameter)

    oversized_exclusion = _manifest()
    oversized_exclusion["metrics"][0]["exclusions"] = ["x" * 513]  # type: ignore[index]
    with pytest.raises(BundleError, match="exclusions"):
        _validate(oversized_exclusion)


def test_runtime_validator_matches_schema_string_bounds_and_rejects_unhashable_items() -> None:
    oversized_version = _manifest()
    oversized_version["metrics"][0]["version"] = "v" * 65  # type: ignore[index]
    with pytest.raises(BundleError, match="metric version"):
        _validate(oversized_version)

    unhashable_dependency = _manifest()
    unhashable_dependency["run"]["dependencies"] = [["not-a-string"]]  # type: ignore[index]
    with pytest.raises(BundleError, match="dependency inventory"):
        _validate(unhashable_dependency)

    unsorted_dependencies = _manifest()
    unsorted_dependencies["run"]["dependencies"] = ["zeta==1", "alpha==1"]  # type: ignore[index]
    with pytest.raises(BundleError, match="dependency inventory"):
        _validate(unsorted_dependencies)

    duplicate_metric = _manifest()
    duplicate_metric["metrics"].append(  # type: ignore[union-attr]
        copy.deepcopy(duplicate_metric["metrics"][0])  # type: ignore[index]
    )
    with pytest.raises(BundleError, match="duplicate identity"):
        _validate(duplicate_metric)

    unsorted_metrics = _manifest()
    second_metric = copy.deepcopy(unsorted_metrics["metrics"][0])  # type: ignore[index]
    second_metric["name"] = "a_metric"
    unsorted_metrics["metrics"].append(second_metric)  # type: ignore[union-attr]
    with pytest.raises(BundleError, match="sorted by family and name"):
        _validate(unsorted_metrics)

    for exclusions in ([""], ["case-b", "case-a"], ["case-a", "case-a"]):
        invalid_exclusions = _manifest()
        invalid_exclusions["metrics"][0]["exclusions"] = exclusions  # type: ignore[index]
        with pytest.raises(BundleError, match="metric exclusions"):
            _validate(invalid_exclusions)

    oversized_operator_role = _manifest()
    oversized_operator_role["disclosures"]["operator_role"] = "o" * 129  # type: ignore[index]
    with pytest.raises(BundleError, match="operator role"):
        _validate(oversized_operator_role)

    disjoint_interval = _manifest()
    disjoint_interval["metrics"][0]["value"] = 0.5  # type: ignore[index]
    disjoint_interval["metrics"][0]["interval"]["low"] = 0.6  # type: ignore[index]
    with pytest.raises(BundleError, match="fall within its interval"):
        _validate(disjoint_interval)


def test_inventory_rejects_reserved_manifest_and_file_directory_collisions() -> None:
    reserved = _manifest()
    reserved["artifacts"]["files"][0][  # type: ignore[index]
        "path"
    ] = "reproducibility-manifest.json"
    with pytest.raises(BundleError, match="cannot own"):
        _validate(reserved)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    path_rules = schema["properties"]["artifacts"]["properties"]["files"][  # type: ignore[index]
        "items"
    ]["properties"]["path"]["allOf"]
    assert {rule["not"]["const"] for rule in path_rules if "not" in rule} == {
        "reproducibility-manifest.json"
    }

    collision = _manifest()
    entry = copy.deepcopy(collision["artifacts"]["files"][0])  # type: ignore[index]
    collision["artifacts"]["files"] = [  # type: ignore[index]
        {**entry, "path": "evidence"},
        {
            **entry,
            "path": "evidence/raw.json",
            "media_type": "application/json",
        },
    ]
    with pytest.raises(BundleError, match="file-directory collision"):
        _validate(collision)

    portable_collision = _manifest()
    entry = copy.deepcopy(portable_collision["artifacts"]["files"][0])  # type: ignore[index]
    portable_collision["artifacts"]["files"] = [  # type: ignore[index]
        {**entry, "path": "Evidence.json", "media_type": "application/json"},
        {**entry, "path": "evidence.JSON", "media_type": "application/json"},
    ]
    with pytest.raises(BundleError, match="non-portable path collision"):
        _validate(portable_collision)


def test_inventory_media_types_are_valid_and_match_core_artifacts() -> None:
    invalid = _manifest()
    invalid["artifacts"]["files"][0]["media_type"] = "not-a-media-type"  # type: ignore[index]
    with pytest.raises(BundleError, match="media type is invalid"):
        _validate(invalid)

    mismatched = _manifest()
    mismatched["artifacts"]["files"][0]["media_type"] = "text/plain"  # type: ignore[index]
    with pytest.raises(BundleError, match="does not match artifact"):
        _validate(mismatched)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    media_type_rule = schema["properties"]["artifacts"]["properties"]["files"][  # type: ignore[index]
        "items"
    ]["properties"]["media_type"]
    assert re.fullmatch(media_type_rule["pattern"], "not-a-media-type") is None


def test_file_inventory_requires_canonical_path_order() -> None:
    manifest = _manifest()
    entry = copy.deepcopy(manifest["artifacts"]["files"][0])  # type: ignore[index]
    manifest["artifacts"]["files"] = [  # type: ignore[index]
        {**entry, "path": "z.txt", "media_type": "text/plain"},
        {**entry, "path": "a.txt", "media_type": "text/plain"},
    ]

    with pytest.raises(BundleError, match="sorted by path"):
        _validate(manifest)


def test_every_recomputed_metric_and_interval_is_bound_to_manifest() -> None:
    declared = [
        {
            "name": "exact_match",
            "version": "1",
            "value": 0.5,
            "numerator": 1.0,
            "denominator": 2,
            "sample_count": 2,
            "interval": {
                "method": "wilson",
                "confidence_level": 0.95,
                "low": 0.1,
                "high": 0.9,
                "parameters": {},
            },
        },
        {
            "name": "token_f1",
            "version": "1",
            "value": 0.75,
            "numerator": None,
            "denominator": None,
            "sample_count": 2,
            "interval": {
                "method": "bootstrap",
                "confidence_level": 0.95,
                "low": 0.5,
                "high": 1.0,
                "parameters": {"iterations": 2000, "seed": 20260728},
            },
        },
    ]
    recomputed = {
        "profile_version": 1,
        "trace_count": 2,
        "metrics": {"exact_match": 0.5, "token_f1": 0.75},
        "intervals": {
            "exact_match": {
                "method": "wilson",
                "confidence": 0.95,
                "low": 0.1,
                "high": 0.9,
            },
            "token_f1": {
                "method": "bootstrap",
                "confidence": 0.95,
                "low": 0.5,
                "high": 1.0,
                "iterations": 2000,
                "seed": 20260728,
            },
        },
    }

    public_bundle._verify_recomputed_metric_declarations(recomputed, declared)
    forged = copy.deepcopy(declared)
    forged[1]["value"] = 0.8
    with pytest.raises(BundleError, match="raw traces"):
        public_bundle._verify_recomputed_metric_declarations(recomputed, forged)


def test_rejects_cyclic_or_excessively_large_manifest_structures() -> None:
    cyclic = _manifest()
    cyclic["cycle"] = cyclic
    with pytest.raises(BundleError, match="cycle"):
        _validate(cyclic)

    oversized = _manifest()
    file_entry = oversized["artifacts"]["files"][0]  # type: ignore[index]
    oversized["artifacts"]["files"] = [  # type: ignore[index]
        {**file_entry, "path": f"traces/{index}.jsonl"}
        for index in range(4097)
    ]
    with pytest.raises(BundleError, match="bounded"):
        _validate(oversized)


def test_rights_and_consent_disclosures_fail_closed() -> None:
    no_rights = _manifest()
    no_rights["disclosures"]["redistribution_permitted"] = False  # type: ignore[index]
    with pytest.raises(BundleError, match="redistribution"):
        _validate(no_rights)

    no_consent = _manifest()
    no_consent["disclosures"]["pii_present"] = True  # type: ignore[index]
    no_consent["disclosures"]["consent_documented"] = False  # type: ignore[index]
    with pytest.raises(BundleError, match="consent"):
        _validate(no_consent)


@pytest.mark.parametrize(
    "path",
    [
        "../traces.jsonl",
        "/traces.jsonl",
        "a\\b",
        "a//b",
        "./a",
        "a/.",
        "a/",
        "C:/escape",
        "evidence/CON.txt",
        "evidence/trailing.",
        "evidence/trailing ",
        "evidence/a:b",
        "evidence/control\x1f",
        "evidence/" + "é" * 128,
        "evidence/e\u0301.json",
        "evidence/\ud800",
    ],
)
def test_inventory_paths_are_normalized_relative_posix_paths(path: str) -> None:
    manifest = _manifest()
    manifest["artifacts"]["files"][0]["path"] = path  # type: ignore[index]
    with pytest.raises(BundleError, match="relative path"):
        _validate(manifest)
    if path not in {
        "evidence/CON.txt",
        "evidence/" + "é" * 128,
        "evidence/e\u0301.json",
        "evidence/\ud800",
    }:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert re.fullmatch(schema["$defs"]["path"]["pattern"], path) is None


def test_verifies_manifest_owned_bytes_and_existing_result_and_replay_contracts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)

    assert public_bundle.verify_reproducibility_bundle(root) == {
        "schema_version": "mnemosyne.reproducibility-bundle/v1",
        "track_kind": "DEVELOPMENT",
        "valid": True,
    }
    assert public_bundle.verify_bundle(root)["schema_version"] == (
        "mnemosyne.reproducibility-bundle/v1"
    )


def test_canonical_replay_seed_records_must_match_run_custody(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    replay = _canonical_replay_payload("wmbs-m10-development")
    (root / "canonical-replay.json").write_bytes(_canonical(replay))
    _refresh_owned_file(root, "canonical-replay.json")
    manifest_path = root / "reproducibility-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["canonical_replay_digest"] = (  # type: ignore[index]
        "sha256:" + public_bundle.canonical_replay_digest(replay)
    )
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="replay seed records do not match run"):
        public_bundle.verify_reproducibility_bundle(root)


@pytest.mark.parametrize(
    "field",
    [
        "bundle_manifest_sha256",
        "fixture_manifest_sha256",
        "generator_manifest_sha256",
    ],
)
def test_canonical_replay_manifests_must_match_retained_artifacts(
    tmp_path: Path, field: str
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    replay_path = root / "canonical-replay.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["manifests"][field] = "d" * 64
    if field == "fixture_manifest_sha256":
        replay["fixture"] = "wmbs-m01-development@sha256:" + "d" * 64
    replay_path.write_bytes(_canonical(replay))
    _refresh_owned_file(root, "canonical-replay.json")
    manifest_path = root / "reproducibility-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["canonical_replay_digest"] = (  # type: ignore[index]
        "sha256:" + public_bundle.canonical_replay_digest(replay)
    )
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="replay manifest custody"):
        public_bundle.verify_reproducibility_bundle(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [("candidate_git_sha", "d" * 40), ("system_seam", "forged-seam")],
)
def test_canonical_replay_build_must_match_run_custody(
    tmp_path: Path, field: str, value: str
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    replay_path = root / "canonical-replay.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["build"][field] = value
    replay_path.write_bytes(_canonical(replay))
    _refresh_owned_file(root, "canonical-replay.json")
    manifest_path = root / "reproducibility-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["canonical_replay_digest"] = (  # type: ignore[index]
        "sha256:" + public_bundle.canonical_replay_digest(replay)
    )
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="replay build custody"):
        public_bundle.verify_reproducibility_bundle(root)


def test_atomic_assembler_packages_and_verifies_owned_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "artifacts"
    destination = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(source)
    (source / "reproducibility-manifest.json").unlink()
    source_mode = (source / "reproduce.sh").stat().st_mode & 0o777

    result = public_bundle.assemble_reproducibility_bundle(
        source, destination, manifest
    )

    assert result["valid"] is True
    assert not source.joinpath("reproducibility-manifest.json").exists()
    assert public_bundle.verify_reproducibility_bundle(destination)["valid"] is True
    if os.name != "nt":
        assert (destination / "reproduce.sh").stat().st_mode & 0o777 == source_mode


def test_atomic_assembler_rejects_source_inventory_drift(tmp_path: Path) -> None:
    source = tmp_path / "artifacts"
    destination = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(source)
    (source / "reproducibility-manifest.json").unlink()
    (source / "unowned.txt").write_text("drift", encoding="utf-8")

    with pytest.raises(BundleError, match="inventory mismatch"):
        public_bundle.assemble_reproducibility_bundle(
            source, destination, manifest
        )
    assert not destination.exists()


def test_atomic_assembler_collision_preserves_external_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "artifacts"
    destination = tmp_path / "bundle"
    sentinel = destination / "external-owner.txt"
    manifest = _write_reproducibility_bundle(source)
    (source / "reproducibility-manifest.json").unlink()
    original_publish = public_bundle._publish_directory_noreplace

    def collide(path: Path, target: Path) -> None:
        if path.name == "final" and target == destination:
            destination.mkdir()
            sentinel.write_text("do not delete", encoding="utf-8")
            raise FileExistsError("simulated assembly destination race")
        original_publish(path, target)

    monkeypatch.setattr(public_bundle, "_publish_directory_noreplace", collide)

    with pytest.raises(FileExistsError, match="assembly destination race"):
        public_bundle.assemble_reproducibility_bundle(
            source, destination, manifest
        )

    assert sentinel.read_text(encoding="utf-8") == "do not delete"
    assert list(tmp_path.glob(".bundle-assemble-*")) == []


def test_atomic_publication_never_replaces_an_empty_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    with pytest.raises(FileExistsError):
        public_bundle._publish_directory_noreplace(source, destination)

    assert source.is_dir()
    assert destination.is_dir()


@pytest.mark.parametrize(
    ("platform_name", "symbol", "expected_flag"),
    [
        ("linux", "renameat2", public_bundle._RENAME_NOREPLACE),
        ("darwin", "renamex_np", public_bundle._RENAME_EXCL),
    ],
)
def test_atomic_publication_dispatches_native_exclusive_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    symbol: str,
    expected_flag: int,
) -> None:
    calls: list[tuple[object, ...]] = []

    class NativeRename:
        argtypes: object = None
        restype: object = None

        def __call__(self, *args: object) -> int:
            calls.append(args)
            return 0

    library = type("Library", (), {symbol: NativeRename()})()
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: library)
    monkeypatch.setattr(public_bundle.os, "name", "posix")
    monkeypatch.setattr(public_bundle.sys, "platform", platform_name)

    public_bundle._publish_directory_noreplace(
        tmp_path / "source", tmp_path / "destination"
    )

    assert len(calls) == 1
    assert calls[0][-1] == expected_flag


def test_atomic_publication_maps_native_collision_to_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NativeRename:
        argtypes: object = None
        restype: object = None

        def __call__(self, *args: object) -> int:
            return -1

    library = type("Library", (), {"renameat2": NativeRename()})()
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: library)
    monkeypatch.setattr(ctypes, "get_errno", lambda: errno.EEXIST)
    monkeypatch.setattr(public_bundle.os, "name", "posix")
    monkeypatch.setattr(public_bundle.sys, "platform", "linux")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        public_bundle._publish_directory_noreplace(
            tmp_path / "source", tmp_path / "destination"
        )


def test_atomic_publication_fails_closed_on_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: object())
    monkeypatch.setattr(public_bundle.os, "name", "posix")
    monkeypatch.setattr(public_bundle.sys, "platform", "unsupported")

    with pytest.raises(BundleError, match="no-replace publication is unavailable"):
        public_bundle._publish_directory_noreplace(
            tmp_path / "source", tmp_path / "destination"
        )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("result", "benchmark", "different-suite"),
        ("identity", "seed", 999),
        ("run_profile", "retries", 1),
        ("publication", "publishable", True),
        ("operator_entry", "operator", "different-operator"),
        ("result", "custody", "operator-held-out"),
        ("result", "signer_role", "independent"),
    ],
)
def test_result_bundle_custody_mismatches_fail_closed(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    benchmark = json.loads((root / "benchmark.json").read_text(encoding="utf-8"))
    target = result if section == "result" else result[section]
    target[field] = value

    with pytest.raises(BundleError, match="embedded bundle custody"):
        public_bundle._verify_result_bundle_bindings(result, manifest, benchmark)


@pytest.mark.parametrize(
    ("field", "value"),
    [("exclusions", ["undisclosed-case"]), ("aborted", 1)],
)
def test_metric_outcome_accounting_must_match_run_custody(
    tmp_path: Path, field: str, value: object
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    benchmark = json.loads((root / "benchmark.json").read_text(encoding="utf-8"))
    metric = manifest["metrics"][0]  # type: ignore[index]
    if field == "exclusions":
        metric[field] = value
    else:
        metric["outcomes"][field] = value

    with pytest.raises(BundleError, match="outcome accounting"):
        public_bundle._verify_result_bundle_bindings(result, manifest, benchmark)


@pytest.mark.parametrize(
    "name", ["build.json", "config.json", "traces.jsonl", "result.json", "uv.lock"]
)
def test_one_byte_tampering_fails_closed(tmp_path: Path, name: str) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    with (root / name).open("ab") as handle:
        handle.write(b"x")

    with pytest.raises(BundleError, match="digest mismatch"):
        public_bundle.verify_reproducibility_bundle(root)


def test_digest_reference_streams_without_path_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"streamed artifact" * 100_000
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(payload)

    def reject_read_bytes(_path: Path) -> bytes:
        raise AssertionError("digest helper must stream")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)

    assert public_bundle._sha256_reference(artifact) == _digest(payload)


def test_size_mismatch_fails_before_hashing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    readme = root / "README.md"
    readme.write_bytes(readme.read_bytes() + b"x")
    original = public_bundle._inspect_artifact

    def guard(path: Path) -> tuple[int, str, bool]:
        if path == readme:
            raise AssertionError("size-mismatched file must not be hashed")
        return original(path)

    monkeypatch.setattr(public_bundle, "_inspect_artifact", guard)

    with pytest.raises(BundleError, match="digest mismatch: README.md"):
        public_bundle.verify_reproducibility_bundle(root)


def test_verifier_rejects_artifact_changed_after_initial_digest_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    readme = root / "README.md"
    original_replay_digest = public_bundle.canonical_replay_digest

    def mutate_after_semantic_verification(payload: object) -> str:
        digest = original_replay_digest(payload)
        readme.write_bytes(readme.read_bytes() + b"changed")
        return digest

    monkeypatch.setattr(
        public_bundle,
        "canonical_replay_digest",
        mutate_after_semantic_verification,
    )

    with pytest.raises(BundleError, match="artifact changed during verification: README.md"):
        public_bundle.verify_reproducibility_bundle(root)


def test_verifier_rejects_same_content_hardlink_added_after_initial_tree_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    readme = root / "README.md"
    external = tmp_path / "external-readme.md"
    original_replay_digest = public_bundle.canonical_replay_digest

    def replace_after_semantic_verification(payload: object) -> str:
        digest = original_replay_digest(payload)
        content = readme.read_bytes()
        readme.unlink()
        external.write_bytes(content)
        os.link(external, readme)
        return digest

    monkeypatch.setattr(
        public_bundle,
        "canonical_replay_digest",
        replace_after_semantic_verification,
    )

    with pytest.raises(BundleError, match="hard-linked files are forbidden"):
        public_bundle.verify_reproducibility_bundle(root)


def test_verifier_rejects_manifest_changed_after_initial_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    manifest_path = root / "reproducibility-manifest.json"
    original_replay_digest = public_bundle.canonical_replay_digest

    def mutate_after_semantic_verification(payload: object) -> str:
        digest = original_replay_digest(payload)
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        return digest

    monkeypatch.setattr(
        public_bundle,
        "canonical_replay_digest",
        mutate_after_semantic_verification,
    )

    with pytest.raises(BundleError, match="manifest changed during verification"):
        public_bundle.verify_reproducibility_bundle(root)


def test_manifest_reader_rejects_hard_link_before_parsing(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    manifest = root / "reproducibility-manifest.json"
    external = tmp_path / "manifest.json"
    external.write_bytes(manifest.read_bytes())
    manifest.unlink()
    os.link(external, manifest)

    with pytest.raises(BundleError, match="manifest must be a real file"):
        public_bundle.verify_reproducibility_bundle(root)


def test_manifest_rejects_secret_like_decoded_values(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    manifest["disclosures"]["operator_identity"] = "sk_live_abcdefghijklmnop"  # type: ignore[index]
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="secret-like material detected"):
        public_bundle.verify_reproducibility_bundle(root)


def test_dependency_disclosures_must_match_digest_bound_lockfile(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    forged_dependencies = ["forged-package==9.9.9"]
    manifest["run"]["dependencies"] = forged_dependencies  # type: ignore[index]
    environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    environment["dependencies"] = forged_dependencies
    environment_payload = _canonical(environment)
    (root / "environment.json").write_bytes(environment_payload)
    manifest["artifacts"]["environment_digest"] = _digest(  # type: ignore[index]
        environment_payload
    )
    for entry in manifest["artifacts"]["files"]:  # type: ignore[index]
        if entry["path"] == "environment.json":
            entry["size"] = len(environment_payload)
            entry["digest"] = _digest(environment_payload)
            break
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="dependency inventory does not match lockfile"):
        public_bundle.verify_reproducibility_bundle(root)


def test_lockfile_dependencies_can_be_parsed_from_bound_bytes() -> None:
    lockfile = Path("uv.lock")

    assert public_bundle._locked_dependencies_from_bytes(
        lockfile.read_bytes()
    ) == public_bundle._locked_dependencies(lockfile)


def test_semantic_digest_bindings_reuse_verified_inventory_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)

    def reject_path_rehash(_path: Path) -> str:
        raise AssertionError("semantic digest bindings must not reopen pathnames")

    monkeypatch.setattr(public_bundle, "_sha256_reference", reject_path_rehash)

    assert public_bundle.verify_reproducibility_bundle(root)["valid"] is True


def test_reproduction_rejects_checkout_lockfile_outside_inventory_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _write_reproducibility_bundle(source)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "uv.lock").write_bytes(b"version = 1\n")
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )

    with pytest.raises(BundleError, match="checkout lockfile digest mismatch"):
        public_bundle.reproduce_reproducibility_bundle(
            source, tmp_path / "reproduced"
        )


def test_inventory_drift_and_symlinks_fail_before_validation(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    (root / "unowned.txt").write_text("drift", encoding="utf-8")
    with pytest.raises(BundleError, match="inventory mismatch"):
        public_bundle.verify_reproducibility_bundle(root)


def test_special_permission_bits_are_classified_as_unsafe() -> None:
    assert public_bundle._UNSAFE_MODE_BITS & 0o7000 == 0o7000
    assert 0o755 & public_bundle._UNSAFE_MODE_BITS == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits required")
def test_special_permission_bits_are_rejected_before_copy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    manifest = _write_reproducibility_bundle(source)
    artifact = source / "reproduce.sh"
    artifact.chmod(artifact.stat().st_mode | stat.S_ISUID)

    with pytest.raises(BundleError, match="special permission bits"):
        public_bundle.verify_reproducibility_bundle(source)

    (source / "reproducibility-manifest.json").unlink()
    with pytest.raises(BundleError, match="special permission bits"):
        public_bundle.assemble_reproducibility_bundle(
            source, tmp_path / "assembled", manifest
        )


def test_atomic_assembler_rejects_file_replaced_after_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    manifest = _write_reproducibility_bundle(source)
    (source / "reproducibility-manifest.json").unlink()
    external = tmp_path / "external.txt"
    external.write_bytes(b"benign external bytes\n")
    entry = next(
        item
        for item in manifest["artifacts"]["files"]  # type: ignore[index]
        if item["path"] == "reproduce.sh"
    )
    entry["size"] = external.stat().st_size
    entry["digest"] = _digest(external.read_bytes())
    original_tree = public_bundle._reproducibility_tree
    swapped = False

    def swap_after_inventory(
        root: Path, expected_files: set[str], expected_directories: set[str]
    ) -> tuple[set[str], set[str]]:
        nonlocal swapped
        result = original_tree(root, expected_files, expected_directories)
        if root == source.resolve() and not swapped:
            swapped = True
            artifact = source / "reproduce.sh"
            artifact.unlink()
            os.link(external, artifact)
        return result

    monkeypatch.setattr(
        public_bundle, "_reproducibility_tree", swap_after_inventory
    )

    with pytest.raises(BundleError, match="changed before copy"):
        public_bundle.assemble_reproducibility_bundle(
            source, tmp_path / "assembled", manifest
        )
    assert not (tmp_path / "assembled").exists()


def test_nested_inventory_paths_verify_and_reproduce_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    manifest = _write_reproducibility_bundle(source)
    nested = source / "evidence" / "raw.bin"
    nested.parent.mkdir()
    payload = b"opaque retained evidence\x00\xff\n"
    nested.write_bytes(payload)
    manifest["artifacts"]["files"].append(  # type: ignore[index]
        {
            "path": "evidence/raw.bin",
            "size": len(payload),
            "media_type": "application/octet-stream",
            "canonicalization": "exact-bytes",
            "digest": _digest(payload),
        }
    )
    manifest["artifacts"]["files"].sort(key=lambda entry: entry["path"])  # type: ignore[index,union-attr]
    (source / "reproducibility-manifest.json").write_bytes(_canonical(manifest))
    original_read_bytes = Path.read_bytes

    def reject_opaque_read_bytes(path: Path) -> bytes:
        if path.name == "raw.bin":
            raise AssertionError("opaque artifacts must be streamed")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_opaque_read_bytes)
    original_read_text = Path.read_text

    def reject_opaque_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "raw.bin":
            raise AssertionError("opaque artifacts must not be decoded wholesale")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_opaque_read_text)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)

    assert public_bundle.verify_reproducibility_bundle(source)["valid"] is True
    public_bundle.reproduce_reproducibility_bundle(source, destination)

    with (destination / "evidence" / "raw.bin").open("rb") as handle:
        assert handle.read() == payload
    assert public_bundle.verify_reproducibility_bundle(destination)["valid"] is True


def test_artifact_inspection_hashes_counts_and_detects_across_chunks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.bin"
    prefix = b"sk_live_"
    payload = (
        b"x" * (public_bundle._SECRET_SCAN_CHUNK_SIZE - len(prefix))
        + prefix
        + b"a" * 16
    )
    path.write_bytes(payload)

    assert public_bundle._inspect_artifact(path) == (
        len(payload),
        _digest(payload),
        True,
    )


def test_artifact_inspection_detects_long_credential_url_across_chunks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.bin"
    credential = (
        b"postgresql://" + b"u" * 256 + b":" + b"p" * 256 + b"@database.example"
    )
    payload = (
        b"x" * (public_bundle._SECRET_SCAN_CHUNK_SIZE - len(credential) // 2)
        + credential
    )
    path.write_bytes(payload)

    assert public_bundle._inspect_artifact(path) == (
        len(payload),
        _digest(payload),
        True,
    )


@pytest.mark.parametrize(
    "credential",
    [
        b"github_pat_" + b"a" * 24,
        b"glpat-" + b"a" * 20,
        b"xoxb-" + b"a" * 12,
        b"AIza" + b"a" * 35,
        b"AKIA" + b"A" * 16,
        b"Authorization: Bearer " + b"a" * 32,
        b"authorization: basic " + b"YWRtaW46c3VwZXJzZWNyZXQ=",
        b"postgresql://public:supersecret@database.example/mnemosyne",
    ],
)
def test_artifact_inspection_rejects_prefixed_credentials(
    tmp_path: Path, credential: bytes
) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"retained evidence: " + credential)

    assert public_bundle._inspect_artifact(path)[2] is True


def test_artifact_inspection_allows_noncredential_prefixes(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(
        b"github_pat_redacted glpat-redacted xoxb-redacted AKIA-redacted "
        b"Bearer redacted Basic redacted https://database.example/mnemosyne"
    )

    assert public_bundle._inspect_artifact(path)[2] is False


def test_artifact_inspection_rejects_hard_linked_path(tmp_path: Path) -> None:
    original = tmp_path / "original.bin"
    linked = tmp_path / "linked.bin"
    original.write_bytes(b"public artifact bytes\n")
    os.link(original, linked)

    with pytest.raises(BundleError, match="changed before inspection"):
        public_bundle._inspect_artifact(linked)
    with pytest.raises(BundleError, match="changed before inspection"):
        public_bundle._sha256_reference(linked)


def test_semantic_artifact_reads_are_bound_to_inventory_bytes(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    expected = _canonical({"state": "expected"})
    path.write_bytes(_canonical({"state": "substituted"}))
    entry = {
        "path": "record.json",
        "size": len(expected),
        "digest": _digest(expected),
    }

    with pytest.raises(BundleError, match="digest mismatch: record.json"):
        public_bundle._load_bound_json(path, entry)
    with pytest.raises(BundleError, match="digest mismatch: record.json"):
        public_bundle._validate_artifact_media(path, "application/json", entry)


def test_signed_ledger_verification_uses_inventory_bound_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    entries = {
        entry["path"]: entry
        for entry in manifest["artifacts"]["files"]  # type: ignore[index]
    }
    from leaderboard import ledger as ledger_module

    original_verify = ledger_module.verify_ledger
    observed: list[tuple[Path, Path]] = []

    def observe_snapshot(ledger_path: Path, public_key_path: Path) -> object:
        observed.append((ledger_path, public_key_path))
        assert ledger_path.parent == public_key_path.parent
        assert ledger_path.parent != root
        assert ledger_path.read_bytes() == (root / "ledger.jsonl").read_bytes()
        assert public_key_path.read_bytes() == (root / "ledger-public.pem").read_bytes()
        return original_verify(ledger_path, public_key_path)

    monkeypatch.setattr(ledger_module, "verify_ledger", observe_snapshot)

    verified, fingerprint = public_bundle._verify_bound_ledger(
        root, entries, "ledger.jsonl", "ledger-public.pem"
    )

    assert verified
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
    assert len(observed) == 1


def test_embedded_legacy_verification_uses_inventory_bound_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    entries = {
        entry["path"]: entry
        for entry in manifest["artifacts"]["files"]  # type: ignore[index]
    }
    original_verify = public_bundle.verify_bundle
    observed: list[Path] = []

    def observe_snapshot(snapshot: Path) -> dict[str, object]:
        observed.append(snapshot)
        assert snapshot != root
        assert (snapshot / "metrics.json").read_bytes() == (
            root / "metrics.json"
        ).read_bytes()
        (root / "metrics.json").write_bytes(b"{}\n")
        return original_verify(snapshot)

    monkeypatch.setattr(public_bundle, "verify_bundle", observe_snapshot)

    result = public_bundle._verify_embedded_legacy_bundle(root, entries)

    assert result["valid"] is True
    assert len(observed) == 1


def test_artifact_secret_scan_handles_large_benign_tokens(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    payload = b"a" * (public_bundle._SECRET_SCAN_CHUNK_SIZE * 2)
    path.write_bytes(payload)

    assert public_bundle._inspect_artifact(path) == (
        len(payload),
        _digest(payload),
        False,
    )


@pytest.mark.parametrize("media_type", ["application/json", "application/x-ndjson"])
def test_artifact_media_rejects_json_escaped_credentials(
    tmp_path: Path, media_type: str
) -> None:
    path = tmp_path / "artifact"
    path.write_text(
        '{"value":"ghp_\\u0061aaaaaaaaaaaaaaaaaaa"}\n', encoding="utf-8"
    )

    assert public_bundle._inspect_artifact(path)[2] is False
    with pytest.raises(BundleError, match="secret-like material detected"):
        public_bundle._validate_artifact_media(path, media_type)


@pytest.mark.parametrize(
    ("media_type", "payload", "message"),
    [
        ("application/json", b"not json", "declared as JSON"),
        ("application/x-ndjson", b'{"ok":true}\n\n', "declared as NDJSON"),
        ("text/plain", b"invalid UTF-8: \xff", "not UTF-8"),
    ],
)
def test_artifact_media_type_is_enforced_against_content(
    tmp_path: Path, media_type: str, payload: bytes, message: str
) -> None:
    path = tmp_path / "artifact"
    path.write_bytes(payload)

    with pytest.raises(BundleError, match=message):
        public_bundle._validate_artifact_media(path, media_type)


def test_reproduction_rejects_linked_source_path(tmp_path: Path) -> None:
    source = tmp_path / "source"
    linked = tmp_path / "linked-source"
    _write_reproducibility_bundle(source)
    try:
        linked.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require additional host privileges")

    with pytest.raises(BundleError, match="links or junctions"):
        public_bundle.reproduce_reproducibility_bundle(
            linked, tmp_path / "reproduced"
        )


def test_verifier_rejects_hard_linked_artifact(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    os.link(root / "README.md", tmp_path / "external-readme.md")

    with pytest.raises(BundleError, match="hard-linked files are forbidden"):
        public_bundle.verify_reproducibility_bundle(root)


def test_signed_ledger_is_cryptographically_verified_after_inventory_check(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    ledger = root / "ledger.jsonl"
    entry = json.loads(ledger.read_text(encoding="utf-8"))
    entry["signature"] = "!" + entry["signature"][1:]
    ledger.write_bytes(_canonical(entry))
    _refresh_owned_file(root, "ledger.jsonl")

    with pytest.raises(BundleError, match="signed-ledger verification"):
        public_bundle.verify_reproducibility_bundle(root)


def test_missing_ledger_lock_fails_without_mutating_bundle(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    lock = root / "ledger.jsonl.lock"
    lock.unlink()
    manifest["artifacts"]["files"] = [  # type: ignore[index]
        entry
        for entry in manifest["artifacts"]["files"]  # type: ignore[index]
        if entry["path"] != lock.name
    ]
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="missing required file: ledger.jsonl.lock"):
        public_bundle.verify_reproducibility_bundle(root)
    assert not lock.exists()


def test_independent_reproduction_requires_distinct_signed_ledger_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    manifest["disclosures"]["independent_reproduction"] = {  # type: ignore[index]
        "receipt_digest": DIGEST,
        "reproducer_identity": "external-reproducer",
        "public_key_digest": DIGEST,
        "signed": True,
    }
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="missing required file"):
        public_bundle.verify_reproducibility_bundle(root)


def test_distinct_signed_ledger_receipt_records_independent_reproduction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    independent_private_key = Ed25519PrivateKey.generate()
    independent_private_path = root.parent / "independent-private.pem"
    independent_public_path = root / "independent-public.pem"
    independent_private_path.write_bytes(
        independent_private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    independent_public_path.write_bytes(
        independent_private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    independent_ledger = root / "independent-ledger.jsonl"
    receipt = append_entry(
        independent_ledger,
        independent_private_path,
        entry_id="independent-repro-entry-1",
        timestamp="2026-09-05T12:01:00Z",
        entrant_id="external-reproducer",
        status="succeeded",
        run_id="external-reproduction-1",
        result=result,
        roster={"external-reproducer"},
    )
    manifest["disclosures"]["independent_reproduction"] = {  # type: ignore[index]
        "receipt_digest": receipt["entry_digest"],
        "reproducer_identity": "external-reproducer",
        "public_key_digest": _digest(independent_public_path.read_bytes()),
        "signed": True,
    }
    for name in (
        "independent-ledger.jsonl",
        "independent-ledger.jsonl.head.json",
        "independent-ledger.jsonl.lock",
        "independent-public.pem",
    ):
        payload = (root / name).read_bytes()
        manifest["artifacts"]["files"].append(  # type: ignore[index]
            {
                "path": name,
                "size": len(payload),
                "media_type": _media_type(name),
                "canonicalization": "exact-bytes",
                "digest": _digest(payload),
            }
        )
    manifest["artifacts"]["files"].sort(key=lambda entry: entry["path"])  # type: ignore[index,union-attr]
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))

    assert public_bundle.verify_reproducibility_bundle(root)["valid"] is True


@pytest.mark.parametrize("pem_suffix", [b"", b"\n"])
def test_independent_reproduction_rejects_operator_signing_key(
    tmp_path: Path, pem_suffix: bytes
) -> None:
    root = tmp_path / "bundle"
    manifest = _write_reproducibility_bundle(root)
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    independent_ledger = root / "independent-ledger.jsonl"
    receipt = append_entry(
        independent_ledger,
        root.parent / "ledger-private.pem",
        entry_id="forged-independent-entry",
        timestamp="2026-09-05T12:01:00Z",
        entrant_id="external-reproducer",
        status="succeeded",
        run_id="forged-independent-run",
        result=result,
        roster={"external-reproducer"},
    )
    (root / "independent-public.pem").write_bytes(
        (root / "ledger-public.pem").read_bytes() + pem_suffix
    )
    manifest["disclosures"]["independent_reproduction"] = {  # type: ignore[index]
        "receipt_digest": receipt["entry_digest"],
        "reproducer_identity": "external-reproducer",
        "public_key_digest": _digest((root / "independent-public.pem").read_bytes()),
        "signed": True,
    }
    for name in (
        "independent-ledger.jsonl",
        "independent-ledger.jsonl.head.json",
        "independent-ledger.jsonl.lock",
        "independent-public.pem",
    ):
        payload = (root / name).read_bytes()
        manifest["artifacts"]["files"].append(  # type: ignore[index]
            {
                "path": name,
                "size": len(payload),
                "media_type": _media_type(name),
                "canonicalization": "exact-bytes",
                "digest": _digest(payload),
            }
        )
    manifest["artifacts"]["files"].sort(key=lambda entry: entry["path"])  # type: ignore[index,union-attr]
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))

    with pytest.raises(BundleError, match="key is not distinct"):
        public_bundle.verify_reproducibility_bundle(root)


def test_reproduction_recomputes_metrics_and_byte_compares_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)
    source_mode = (source / "reproduce.sh").stat().st_mode & 0o777
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)

    result = public_bundle.reproduce_bundle(source, destination)

    assert result["schema_version"] == "mnemosyne.reproducibility-bundle/v1"
    assert public_bundle.verify_reproducibility_bundle(destination)["valid"] is True
    assert {
        entry.name: entry.read_bytes() for entry in source.iterdir()
    } == {entry.name: entry.read_bytes() for entry in destination.iterdir()}
    if os.name != "nt":
        assert (destination / "reproduce.sh").stat().st_mode & 0o777 == source_mode


def test_reproduction_uses_one_inventory_bound_source_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)
    expected_metrics = (source / "metrics.json").read_bytes()
    original_copy = public_bundle._copy_inventory_artifact
    mutated = False
    metrics_copies = 0

    def mutate_source_after_metrics_snapshot(
        source_file: Path, target: Path, entry: dict[str, object]
    ) -> None:
        nonlocal metrics_copies, mutated
        original_copy(source_file, target, entry)
        if source_file == source / "metrics.json":
            metrics_copies += 1
            if metrics_copies == 2:
                (source / "metrics.json").write_bytes(b"{}\n")
                mutated = True

    monkeypatch.setattr(
        public_bundle, "_copy_inventory_artifact", mutate_source_after_metrics_snapshot
    )
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)

    result = public_bundle.reproduce_bundle(source, destination)

    assert mutated is True
    assert result["valid"] is True
    assert (destination / "metrics.json").read_bytes() == expected_metrics


def test_reproduction_rejects_manifest_change_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)
    original_verify = public_bundle.verify_reproducibility_bundle

    def replace_manifest_after_verification(bundle: Path | str) -> dict[str, object]:
        result = original_verify(bundle)
        if Path(bundle) == source:
            (source / "reproducibility-manifest.json").write_bytes(
                _canonical({"artifacts": {"files": [{"path": "../../escape"}]}})
            )
        return result

    monkeypatch.setattr(
        public_bundle,
        "verify_reproducibility_bundle",
        replace_manifest_after_verification,
    )
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)

    with pytest.raises(BundleError, match="manifest changed during reproduction"):
        public_bundle.reproduce_bundle(source, destination)
    assert not tmp_path.joinpath("escape").exists()
    assert not destination.exists()


def test_reproduction_rejects_dirty_or_wrong_checkout_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)

    def reject(_sha: str) -> None:
        raise BundleError("reproduction checkout is dirty")

    monkeypatch.setattr(public_bundle, "_require_clean_reproduction_checkout", reject)
    _clear_credential_environment(monkeypatch)
    with pytest.raises(BundleError, match="dirty"):
        public_bundle.reproduce_bundle(source, destination)
    assert not destination.exists()


def test_checkout_verification_uses_a_sanitized_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environments: list[dict[str, str]] = []
    commands: list[list[str]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "attacker-repository"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "attacker-config"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "attacker-worktree"))

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        environments.append(environment)
        commands.append(command)
        if "symbolic-ref" in command:
            stdout = ""
            returncode = 1
        elif command[-1] == "HEAD":
            stdout = GIT_SHA + "\n"
            returncode = 0
        elif command[-1] == "--show-toplevel":
            stdout = str(tmp_path) + "\n"
            returncode = 0
        elif "status" in command and command[-1] == "--porcelain":
            stdout = ""
            returncode = 0
        else:
            raise AssertionError(f"unexpected Git command: {command}")
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    monkeypatch.setattr(public_bundle.subprocess, "run", run)

    public_bundle._require_clean_reproduction_checkout(GIT_SHA)

    assert len(environments) == 4
    assert all("GIT_DIR" not in environment for environment in environments)
    assert all(
        environment["GIT_CONFIG_GLOBAL"] == os.devnull for environment in environments
    )
    assert all(
        environment["GIT_CONFIG_SYSTEM"] == os.devnull for environment in environments
    )
    assert all(environment["GIT_OPTIONAL_LOCKS"] == "0" for environment in environments)
    assert all(
        environment["GIT_WORK_TREE"] == str(tmp_path.resolve())
        for environment in environments
    )
    assert all(
        environment["GIT_CONFIG_NOSYSTEM"] == "1" for environment in environments
    )
    assert all(
        command[:5]
        == [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
        ]
        for command in commands
    )


def test_reproduction_requires_offline_mode_and_rejects_inherited_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _write_reproducibility_bundle(source)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)
    monkeypatch.delenv("UV_OFFLINE")
    with pytest.raises(BundleError, match="UV_OFFLINE"):
        public_bundle.reproduce_bundle(source, tmp_path / "online")
    assert not (tmp_path / "online").exists()

    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("EXAMPLE_API_TOKEN", "not-even-a-real-secret")
    with pytest.raises(BundleError, match="inherited credentials"):
        public_bundle.reproduce_bundle(source, tmp_path / "credentialed")
    assert not (tmp_path / "credentialed").exists()

    monkeypatch.delenv("EXAMPLE_API_TOKEN")
    monkeypatch.setenv("OPENAI_API_KEY", "not-even-a-real-secret")
    with pytest.raises(BundleError, match="inherited credentials"):
        public_bundle.reproduce_bundle(source, tmp_path / "api-key-credentialed")
    assert not (tmp_path / "api-key-credentialed").exists()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PYTHONHASHSEED", "1", "allowlist"),
        ("UV_RUN_RECURSION_DEPTH", "2", "isolated uv run"),
        ("LC_ALL", "en_US.UTF-8", "locale or timezone"),
        ("TZ", "Europe/London", "locale or timezone"),
    ],
)
def test_reproduction_requires_manifest_bound_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    source = tmp_path / "source"
    _write_reproducibility_bundle(source)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(BundleError, match=message):
        public_bundle.reproduce_reproducibility_bundle(
            source, tmp_path / f"reproduced-{name.lower()}"
        )


@pytest.mark.parametrize("name", ["PYTHONPATH", "UV_INDEX_URL", "HTTPS_PROXY", "GIT_DIR"])
def test_reproduction_rejects_undeclared_execution_influences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    source = tmp_path / "source"
    _write_reproducibility_bundle(source)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)
    monkeypatch.setenv(name, "attacker-controlled")

    with pytest.raises(BundleError, match="undeclared influences"):
        public_bundle.reproduce_reproducibility_bundle(
            source, tmp_path / f"influenced-{name.lower()}"
        )


def test_reproduction_drift_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)
    original = public_bundle._recompute_bundle_metrics
    calls = 0

    def drifted(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        metrics = original(*args, **kwargs)
        if calls == 2:
            metrics = {**metrics, "value": 0.0}
        return metrics

    monkeypatch.setattr(public_bundle, "_recompute_bundle_metrics", drifted)
    with pytest.raises(BundleError, match="reproduction mismatch"):
        public_bundle.reproduce_bundle(source, destination)
    assert not destination.exists()


def test_destination_collision_race_never_deletes_external_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    sentinel = destination / "external-owner.txt"
    _write_reproducibility_bundle(source)
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)
    original_publish = public_bundle._publish_directory_noreplace

    def collide(path: Path, target: Path) -> None:
        if path.name == "final" and target == destination:
            destination.mkdir()
            sentinel.write_text("do not delete", encoding="utf-8")
            raise FileExistsError("simulated destination race")
        original_publish(path, target)

    monkeypatch.setattr(public_bundle, "_publish_directory_noreplace", collide)
    with pytest.raises(FileExistsError, match="destination race"):
        public_bundle.reproduce_reproducibility_bundle(source, destination)

    assert sentinel.read_text(encoding="utf-8") == "do not delete"


def test_exact_command_reproduces_from_clean_detached_offline_checkout(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv executable is required for the clean-checkout contract")
    source = tmp_path / "source-bundle"
    checkout = tmp_path / "checkout"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)
    repository = Path(__file__).parents[1]
    subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", str(repository), str(checkout)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "checkout", "--detach", GIT_SHA],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    subprocess.run(
        [uv, "sync", "--locked", "--offline"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if not public_bundle._credential_environment_name(name)
        and not public_bundle._undeclared_influential_environment_name(
            name, {"PYTHONHASHSEED"}
        )
    }
    environment.pop("UV_RUN_RECURSION_DEPTH", None)
    environment.update(
        {
            "PATH": str(Path(uv).parent) + os.pathsep + environment.get("PATH", ""),
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C",
            "TZ": "UTC",
            "UV_OFFLINE": "1",
        }
    )
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "--isolated",
            "mneme",
            "eval-public",
            "--reproduce-bundle",
            str(source),
            "--out-dir",
            str(destination),
        ],
        cwd=checkout,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["valid"] is True
    assert subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout == ""
    assert {entry.name: entry.read_bytes() for entry in source.iterdir()} == {
        entry.name: entry.read_bytes() for entry in destination.iterdir()
    }
