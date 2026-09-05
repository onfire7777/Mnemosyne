from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eval.public import bundle as public_bundle
from eval.public.bundle import BundleError
from leaderboard.ledger import append_entry
from eval.public.runner import run_public_suite
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


def _write_reproducibility_bundle(root: Path) -> dict[str, object]:
    run_public_suite("smoke", root)
    payloads = {entry.name: entry.read_bytes() for entry in root.iterdir()}
    payloads.update(
        {
            "environment.json": _canonical(
                {
                    "platform": PLATFORM,
                    "runtime": RUNTIME,
                    "dependencies": ["mnemosyne==0.1.0"],
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
    record["run_commit"] = GIT_SHA
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
    payloads["result.json"] = _canonical(record)
    replay = _canonical_replay_payload("wmbs-m01-development")
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
        if any(
            marker in name.upper()
            for marker in ("TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY")
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UV_OFFLINE", "1")


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
    (source / "reproducibility-manifest.json").write_bytes(_canonical(manifest))
    monkeypatch.setattr(
        public_bundle, "_require_clean_reproduction_checkout", lambda _sha: None
    )
    _clear_credential_environment(monkeypatch)

    assert public_bundle.verify_reproducibility_bundle(source)["valid"] is True
    public_bundle.reproduce_reproducibility_bundle(source, destination)

    assert (destination / "evidence" / "raw.bin").read_bytes() == payload
    assert public_bundle.verify_reproducibility_bundle(destination)["valid"] is True


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


def test_reproduction_recomputes_legacy_outputs_and_byte_compares_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reproduced"
    _write_reproducibility_bundle(source)
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
        if not any(
            marker in name.upper()
            for marker in ("TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY")
        )
    }
    environment.update(
        {
            "PATH": str(Path(uv).parent) + os.pathsep + environment.get("PATH", ""),
            "PYTHONHASHSEED": "0",
            "UV_OFFLINE": "1",
        }
    )
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "mneme",
            "eval-public",
            "--reproduce-bundle",
            str(source),
            "--out-dir",
            str(destination),
        ],
        cwd=checkout,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
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
