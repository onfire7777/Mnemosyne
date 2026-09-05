from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from eval.public import bundle as public_bundle
from eval.public.bundle import BundleError
from tests.test_leaderboard_result_contract import _v2_development_record
from tests.test_public_eval import _canonical_replay_payload


DIGEST = "sha256:" + "a" * 64
COMMAND = [
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
SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "eval"
    / "public"
    / "schema"
    / "reproducibility-bundle-v1.schema.json"
)


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


def _write_reproducibility_bundle(root: Path) -> dict[str, object]:
    root.mkdir()
    payloads = {
        "build.json": _canonical({"candidate_git_sha": "b" * 40}),
        "config.json": _canonical({"locale": "C", "timezone": "UTC"}),
        "bundle-manifest.json": _canonical({"files": {}, "version": 1}),
        "traces.jsonl": _canonical({"question_id": "q1", "score": 1.0}),
        "environment.json": _canonical({"dependencies": ["mnemosyne==0.1.0"]}),
        "uv.lock": b"version = 1\n",
    }
    record = _v2_development_record()
    record["build_fingerprint"] = _digest(payloads["build.json"])
    record["config_digest"] = _digest(payloads["config.json"])
    record["bundle_digest"] = _digest(payloads["bundle-manifest.json"])
    record["trace_index_digest"] = _digest(payloads["traces.jsonl"])
    payloads["result.json"] = _canonical(record)
    replay = _canonical_replay_payload("wmbs-m01-development")
    payloads["canonical-replay.json"] = _canonical(replay)
    ledger_entry = {
        "entry_digest": DIGEST,
        "result": record,
        "status": "succeeded",
    }
    payloads["ledger-entry.json"] = _canonical(ledger_entry)
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)

    manifest = _manifest()
    manifest["result_ref"] = {
        "record_id": record["record_id"],
        "result_digest": _digest(payloads["result.json"]),
        "ledger_entry_digest": DIGEST,
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
                    "media_type": "application/json"
                    if name.endswith(".json")
                    else "text/plain",
                    "canonicalization": "exact-bytes",
                    "digest": _digest(payload),
                }
                for name, payload in sorted(payloads.items())
            ],
        }
    )
    (root / "reproducibility-manifest.json").write_bytes(_canonical(manifest))
    return manifest


def _manifest(*, track_kind: str = "DEVELOPMENT") -> dict[str, object]:
    lineage: dict[str, object]
    if track_kind == "OFFICIAL-UPSTREAM":
        lineage = {"fidelity_manifest_digest": DIGEST}
    elif track_kind == "ENHANCED-SUCCESSOR":
        lineage = {
            "difference_manifest_digest": DIGEST,
            "parent_construct_digest": DIGEST,
            "parent_official_record_id": "official-result-1",
        }
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
            "candidate_git_sha": "b" * 40,
            "dirty": False,
            "platform": "linux-x86_64",
            "runtime": "cpython-3.12",
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
            "source_revision": "b" * 40,
            "redistribution_permitted": True,
            "pii_present": False,
            "consent_documented": True,
            "takedown_process": "security@example.invalid",
            "custody_class": "PUBLIC-SYNTHETIC",
            "operator_identity": "development-test",
            "operator_role": "test-operator",
            "signer_role": "development-signer",
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


def test_accepts_closed_development_manifest() -> None:
    assert _validate(_manifest())["track_kind"] == "DEVELOPMENT"


@pytest.mark.parametrize("track_kind", ["OFFICIAL-UPSTREAM", "ENHANCED-SUCCESSOR"])
def test_accepts_each_lineage_without_blending(track_kind: str) -> None:
    assert _validate(_manifest(track_kind=track_kind))[
        "track_kind"
    ] == track_kind


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


@pytest.mark.parametrize("path", ["../traces.jsonl", "/traces.jsonl", "a\\b"])
def test_inventory_paths_are_normalized_relative_posix_paths(path: str) -> None:
    manifest = _manifest()
    manifest["artifacts"]["files"][0]["path"] = path  # type: ignore[index]
    with pytest.raises(BundleError, match="relative path"):
        _validate(manifest)


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


def test_inventory_drift_and_symlinks_fail_before_validation(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_reproducibility_bundle(root)
    (root / "unowned.txt").write_text("drift", encoding="utf-8")
    with pytest.raises(BundleError, match="inventory mismatch"):
        public_bundle.verify_reproducibility_bundle(root)
