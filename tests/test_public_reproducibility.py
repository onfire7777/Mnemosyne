"""REPRO-001: closed reproducibility-bundle/v1 contract and fail-closed dispatch."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from eval.public.bundle import (
    REQUIRED,
    BundleError,
    _canonical,
    canonical_replay_digest,
    reproduce_bundle,
    verify_bundle,
    write_bundle,
)
from leaderboard.ledger import _canonical as ledger_canonical
from leaderboard.ledger import append_entry, verify_ledger
from leaderboard.validate import (
    DIGEST_PAYLOAD_NAMES,
    SCHEMA_VERSION,
    validate_record,
    verify_result_digests,
)
from tests.test_leaderboard_result_contract import (
    _retrieval_record,
    _v2_development_record,
    _v2_official_record,
    _v2_successor_record,
)
from tests.test_public_eval import (
    REPLAY_DIGESTS,
    _canonical_replay_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPRO_SCHEMA_PATH = REPO_ROOT / "eval/public/schema/reproducibility-bundle-v1.schema.json"
REPRO_SCHEMA_ID = "mnemosyne.reproducibility-bundle/v1"
REPRO_MANIFEST_NAME = "reproducibility-bundle.json"
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
RESULT_V1_SCHEMA_SHA256 = (
    "22544dbcfbad5f09cc4bccbbfd6b79f4bda1b70d2a903f6908cd89cfd3e51817"
)
RESULT_V1_RECORD_CANONICAL_SHA256 = (
    "d69c668ba042eb32a18553fc1e56f8b932df1ae4c301067267a3c6b0c2f81640"
)
V1_BUNDLE_CONCAT_SHA256 = (
    "fb260088a2678b5148f206d0b05d86648b796f6e485b5d8e28d37f1833b51df1"
)
TRACK_KINDS = ("OFFICIAL-UPSTREAM", "ENHANCED-SUCCESSOR", "DEVELOPMENT")
REQUIRED_REPRO_FIELDS = (
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
REQUIRED_MANIFEST_REFS = (
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
REQUIRED_METRIC_FIELDS = (
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
REQUIRED_RIGHTS_FIELDS = (
    "software_license",
    "data_license",
    "source_revision",
    "redistribution",
    "pii",
    "consent",
    "takedown",
    "disclosure_state",
)
REQUIRED_HASH_FIELDS = (
    "path",
    "size",
    "media_type",
    "canonicalization",
    "sha256",
)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_ref(data: bytes) -> str:
    return "sha256:" + _sha256_hex(data)


def _named_ref(name: str, data: bytes) -> str:
    return f"{name}@sha256:{_sha256_hex(data)}"


def _write_json(path: Path, value: object) -> bytes:
    raw = _canonical(value)
    path.write_bytes(raw)
    return raw


def _v1_snapshot_bundle_inputs() -> dict[str, Any]:
    return {
        "benchmark": {
            "k": 1,
            "questions": [{"question_id": "q1", "gold_doc_ids": ["d1"]}],
            "corpus": [{"doc_id": "d1", "text": "doc"}],
        },
        "metadata": {
            "family": "deterministic-retrieval",
            "interval_method": "wilson",
            "scoring_profile": "smoke-hit-at-k-v1",
            "suite": "smoke",
            "dataset_sha256": (
                "ee2220bf82175e38ca44db4b82dbe369b74c83b4d40e784f2d834c99b7d43375"
            ),
        },
        "metrics": {
            "family": "deterministic-retrieval",
            "metric": "hit_at_k",
            "successes": 1,
            "total": 1,
            "trace_count": 1,
            "value": 1.0,
            "interval": {
                "confidence": 0.95,
                "high": 1.0,
                "low": 0.2,
                "method": "wilson",
            },
        },
        "traces": [
            {
                "question_id": "q1",
                "gold_references": ["d1"],
                "stored_records": ["d1"],
                "ranked_retrieved_hits": ["d1"],
                "answer": "d1",
                "scoring_family": "deterministic-retrieval",
            }
        ],
    }


def test_result_v1_schema_bytes_remain_frozen() -> None:
    digest = _sha256_hex(Path("leaderboard/schema/result-v1.schema.json").read_bytes())
    assert digest == RESULT_V1_SCHEMA_SHA256
    assert SCHEMA_VERSION == "mnemosyne.leaderboard.result/v1"


def test_result_v1_validator_and_canonical_ledger_bytes_remain_frozen() -> None:
    record = _retrieval_record()
    assert validate_record(record) == []
    assert _sha256_hex(ledger_canonical(record)) == RESULT_V1_RECORD_CANONICAL_SHA256
    invalid = _retrieval_record()
    metrics = invalid["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["family"] = "unknown"
    assert validate_record(invalid) == ["/metrics/0/family"]


def test_version_1_public_bundle_output_bytes_remain_frozen(tmp_path: Path) -> None:
    inputs = _v1_snapshot_bundle_inputs()
    destination = tmp_path / "v1-bundle"
    write_bundle(destination, **inputs)
    files = tuple(sorted(path.name for path in destination.iterdir()))
    assert files == tuple(sorted((*REQUIRED, "bundle-manifest.json")))
    concat = b"".join((destination / name).read_bytes() for name in files)
    assert _sha256_hex(concat) == V1_BUNDLE_CONCAT_SHA256
    manifest = json.loads((destination / "bundle-manifest.json").read_text())
    assert manifest["version"] == 1
    assert set(manifest["files"]) == set(REQUIRED)


def test_m15_helpers_are_reused_not_copied() -> None:
    payload = _canonical_replay_payload("wmbs-m01-development")
    assert canonical_replay_digest(payload) == REPLAY_DIGESTS["wmbs-m01-development"]
    source = Path("tests/test_public_reproducibility.py").read_text(encoding="utf-8")
    assert "REPLAY_DIGESTS" in source
    assert "_canonical_replay_payload" in source


def test_existing_version_1_verify_does_not_import_new_names() -> None:
    from eval.public import bundle as public_bundle

    assert hasattr(public_bundle, "verify_bundle")
    assert hasattr(public_bundle, "reproduce_bundle")
    assert hasattr(public_bundle, "canonical_replay_digest")


def _load_repro_schema() -> dict[str, Any]:
    raw = REPRO_SCHEMA_PATH.read_bytes()
    schema = json.loads(raw.decode("utf-8"))
    assert isinstance(schema, dict)
    return schema


def _assert_objects_closed(node: object, path: str = "$") -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
        for key, child in node.items():
            if key in {
                "properties",
                "$defs",
                "if",
                "then",
                "else",
                "not",
                "dependentSchemas",
            }:
                _assert_objects_closed(child, f"{path}.{key}")
            elif key in {"allOf", "anyOf", "oneOf", "prefixItems"}:
                assert isinstance(child, list)
                for index, item in enumerate(child):
                    _assert_objects_closed(item, f"{path}.{key}[{index}]")
            elif key == "items":
                _assert_objects_closed(child, f"{path}.items")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _assert_objects_closed(item, f"{path}[{index}]")


def _m02_replay_payload() -> dict[str, object]:
    payload = _canonical_replay_payload("wmbs-m01-development")
    fixture_digest = "2" * 64
    payload["suite"] = "wmbs-m02-retrieval-development"
    payload["seed_records"] = [20260801]
    payload["fixture"] = f"wmbs-m02-retrieval-development@sha256:{fixture_digest}"
    manifests = payload["manifests"]
    assert isinstance(manifests, dict)
    manifests["fixture_manifest_sha256"] = fixture_digest
    return payload


def _result_for_track(
    track_kind: str,
    *,
    artifacts: dict[str, bytes],
    run_commit: str,
) -> dict[str, object]:
    if track_kind == "OFFICIAL-UPSTREAM":
        record = _v2_official_record()
    elif track_kind == "ENHANCED-SUCCESSOR":
        record = _v2_successor_record()
    elif track_kind == "DEVELOPMENT":
        record = _v2_development_record()
    else:
        raise AssertionError(track_kind)
    record["run_commit"] = run_commit
    for field, name in DIGEST_PAYLOAD_NAMES.items():
        record[field] = _sha256_ref(artifacts[name])
    assert validate_record(record) == []
    assert verify_result_digests(record, artifacts) == []
    return record


def _metric_record() -> dict[str, object]:
    return {
        "family": "retrieval",
        "name": "hit_at_k",
        "version": "smoke-hit-at-k-v1",
        "value": 1.0,
        "unit": "ratio",
        "numerator": 1,
        "denominator": 1,
        "sample_count": 1,
        "uncertainty_method": "wilson",
        "uncertainty_parameters": {"z": 1.96},
        "confidence_level": 0.95,
        "interval": {"low": 0.2, "high": 1.0},
        "exclusions": [],
        "missing_count": 0,
        "unsupported_count": 0,
        "failed_count": 0,
        "aborted_count": 0,
        "not_measured_count": 0,
    }


def _write_reproducibility_bundle(
    root: Path,
    *,
    track_kind: str = "DEVELOPMENT",
    include_ledger: bool = True,
    run_commit: str | None = None,
    dirty: bool = False,
    command: list[str] | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True)
    commit = run_commit or "0123456789abcdef0123456789abcdef01234567"
    traces = (
        b'{"answer":"d1","gold_references":["d1"],"question_id":"q1",'
        b'"ranked_retrieved_hits":["d1"],"scoring_family":"deterministic-retrieval",'
        b'"stored_records":["d1"]}\n'
    )
    config = _canonical(
        {
            "family": "deterministic-retrieval",
            "interval_method": "wilson",
            "locale": "C",
            "scoring_profile": "smoke-hit-at-k-v1",
            "suite": "smoke",
            "timezone": "UTC",
        }
    )
    build = _canonical(
        {
            "candidate_git_sha": commit,
            "dirty": dirty,
            "environment_contract": "uv run --locked",
            "lockfile": "uv.lock",
            "system_seam": "public-cli-subprocess",
            "toolchain": "uv",
            "version": 1,
        }
    )
    environment = {
        "allowlist": ["HOME", "LANG", "LC_ALL", "PATH", "TZ", "UV_CACHE_DIR"],
        "dependency_versions": {"uv": "locked"},
        "locale": "C",
        "platform": "linux",
        "runtime": "cpython-3.12",
        "timezone": "UTC",
        "wheelhouse_digest": None,
    }
    metrics_payload = {
        "family": "deterministic-retrieval",
        "interval": {"confidence": 0.95, "high": 1.0, "low": 0.2, "method": "wilson"},
        "metric": "hit_at_k",
        "successes": 1,
        "total": 1,
        "trace_count": 1,
        "value": 1.0,
    }
    replay = _m02_replay_payload()
    supporting = {
        "adapter.json": {"id": "smoke", "kind": "adapter"},
        "baseline.json": {"id": "none", "kind": "baseline"},
        "benchmark-ref.json": {"id": "smoke", "kind": "benchmark"},
        "dataset-split.json": {"id": "development-self-test", "kind": "dataset-split"},
        "fixture-ref.json": {"id": "smoke", "kind": "fixture"},
        "generator.json": {"id": "registry", "kind": "generator"},
        "judge-ref.json": {"id": None, "kind": "judge"},
        "model-ref.json": {"id": None, "kind": "model"},
        "prompt-ref.json": {"id": None, "kind": "prompt"},
        "reader-ref.json": {"id": None, "kind": "reader"},
        "scorer.json": {"id": "smoke-hit-at-k-v1", "kind": "scorer"},
        "environment.json": environment,
        "metrics.json": metrics_payload,
        "canonical-replay.json": replay,
    }
    if track_kind == "OFFICIAL-UPSTREAM":
        supporting["fidelity.json"] = {
            "kind": "fidelity",
            "upstream_protocol_digest": f"sha256:{'c' * 64}",
        }
    if track_kind == "ENHANCED-SUCCESSOR":
        supporting["parent.json"] = {"kind": "parent", "record_id": "synthetic-v2-official-001"}
        supporting["difference.json"] = {"kind": "difference", "summary": "enhanced"}
    written: dict[str, bytes] = {
        "build.json": build,
        "config.json": config,
        "traces.jsonl": traces,
    }
    for name, value in supporting.items():
        written[name] = _write_json(root / name, value)
    (root / "traces.jsonl").write_bytes(traces)
    (root / "config.json").write_bytes(config)
    (root / "build.json").write_bytes(build)
    (root / "uv.lock").write_text("locked-wheelhouse\n", encoding="utf-8")
    written["uv.lock"] = (root / "uv.lock").read_bytes()

    inventory_files = {
        name: _sha256_hex(payload)
        for name, payload in written.items()
        if name != REPRO_MANIFEST_NAME
    }
    bundle_manifest = _write_json(
        root / "bundle-manifest.json",
        {"files": inventory_files, "version": 1},
    )
    written["bundle-manifest.json"] = bundle_manifest
    artifacts = {
        "build.json": written["build.json"],
        "config.json": written["config.json"],
        "bundle-manifest.json": written["bundle-manifest.json"],
        "traces.jsonl": written["traces.jsonl"],
    }
    result = _result_for_track(track_kind, artifacts=artifacts, run_commit=commit)
    result_bytes = _write_json(root / "result.json", result)
    written["result.json"] = result_bytes

    ledger_ref: str | None = None
    if include_ledger:
        private = Ed25519PrivateKey.generate()
        private_path = root / "ledger-private.pem"
        public_path = root / "ledger-public.pem"
        private_path.write_bytes(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        public_path.write_bytes(
            private.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        ledger_path = root / "ledger.jsonl"
        entry = append_entry(
            ledger_path,
            private_path,
            entry_id="repro-001-entry",
            timestamp="2026-09-05T00:00:00Z",
            entrant_id="synthetic-entrant",
            status="succeeded",
            run_id="run-repro-001",
            result=result,
            roster={"synthetic-entrant"},
        )
        private_path.unlink()
        written["ledger.jsonl"] = ledger_path.read_bytes()
        written["ledger.jsonl.head.json"] = ledger_path.with_suffix(
            ledger_path.suffix + ".head.json"
        ).read_bytes()
        written["ledger-public.pem"] = public_path.read_bytes()
        ledger_ref = _named_ref("ledger-entry", ledger_canonical(entry))
        assert verify_ledger(ledger_path, public_path)[0]["entry_id"] == "repro-001-entry"
        for leftover in root.glob("*.jsonl.lock"):
            leftover.unlink()

    hashes = []
    for name, payload in sorted(written.items()):
        hashes.append(
            {
                "path": name,
                "size": len(payload),
                "media_type": (
                    "application/jsonl"
                    if name.endswith(".jsonl")
                    else "application/x-pem-file"
                    if name.endswith(".pem")
                    else "text/plain"
                    if name == "uv.lock"
                    else "application/json"
                ),
                "canonicalization": "raw-bytes",
                "sha256": _sha256_ref(payload),
            }
        )

    manifests = {
        "adapter": _named_ref("adapter", written["adapter.json"]),
        "baseline": _named_ref("baseline", written["baseline.json"]),
        "benchmark": _named_ref("benchmark", written["benchmark-ref.json"]),
        "dataset_split": _named_ref("dataset-split", written["dataset-split.json"]),
        "difference": (
            _named_ref("difference", written["difference.json"])
            if "difference.json" in written
            else None
        ),
        "fidelity": (
            _named_ref("fidelity", written["fidelity.json"])
            if "fidelity.json" in written
            else None
        ),
        "fixture": _named_ref("fixture", written["fixture-ref.json"]),
        "generator": _named_ref("generator", written["generator.json"]),
        "judge": _named_ref("judge", written["judge-ref.json"]),
        "model": _named_ref("model", written["model-ref.json"]),
        "parent": (
            _named_ref("parent", written["parent.json"])
            if "parent.json" in written
            else None
        ),
        "prompt": _named_ref("prompt", written["prompt-ref.json"]),
        "reader": _named_ref("reader", written["reader-ref.json"]),
        "scorer": _named_ref("scorer", written["scorer.json"]),
    }
    metric = _metric_record()
    publication = {
        "certified": False,
        "headline": False,
        "independent": False,
        "independent_external_reproduction": False,
        "pbpp_headline_eligible": False,
        "publishable": False,
    }
    if track_kind == "DEVELOPMENT":
        lineage: dict[str, object] = {}
    elif track_kind == "OFFICIAL-UPSTREAM":
        lineage = deepcopy(_v2_official_record()["lineage"])  # type: ignore[arg-type]
    else:
        lineage = deepcopy(_v2_successor_record()["lineage"])  # type: ignore[arg-type]
    manifest = {
        "schema_version": REPRO_SCHEMA_ID,
        "result_ref": _named_ref("result-v2", result_bytes),
        "ledger_ref": ledger_ref,
        "manifests": manifests,
        "traces": {
            "path": "traces.jsonl",
            "trace_index_digest": _sha256_ref(traces),
            "seed_records": [20260801],
            "retries": 0,
            "aborts": 0,
        },
        "config": {
            "path": "config.json",
            "config_digest": _sha256_ref(config),
            "locale": "C",
            "timezone": "UTC",
        },
        "build": {
            "path": "build.json",
            "build_fingerprint": _sha256_ref(build),
            "candidate_git_sha": commit,
            "dirty": dirty,
            "lockfile": _named_ref("uv.lock", written["uv.lock"]),
            "toolchain": "uv",
            "environment_contract": "uv run --locked",
        },
        "environment": {
            "path": "environment.json",
            "allowlist": environment["allowlist"],
            "locale": "C",
            "timezone": "UTC",
            "platform": "linux",
            "runtime": "cpython-3.12",
            "wheelhouse_digest": None,
        },
        "metrics": [metric],
        "intervals": [
            {
                "metric": "hit_at_k",
                "method": "wilson",
                "confidence_level": 0.95,
                "low": 0.2,
                "high": 1.0,
            }
        ],
        "hashes": hashes,
        "rights": {
            "software_license": "Apache-2.0",
            "data_license": "CC0-1.0",
            "source_revision": commit,
            "redistribution": "allowed-with-attribution",
            "pii": "none",
            "consent": "not-applicable",
            "takedown": "repository-issue",
            "disclosure_state": "disclosed",
        },
        "custody": {
            "class": "development-public",
            "declaration": "synthetic-public-fixtures",
        },
        "operator": {
            "identity": "synthetic-test",
            "role": "operator",
            "signer_role": "operator",
            "disclosure_state": "disclosed",
        },
        "command": list(command or REPRODUCTION_ARGV),
        "track_kind": track_kind,
        "lineage": lineage,
        "canonical_replay": {
            "suite": "wmbs-m02-retrieval-development",
            "digest": canonical_replay_digest(replay),
            "seed_records": [20260801],
        },
        "publication": publication,
    }
    _write_json(root / REPRO_MANIFEST_NAME, manifest)
    return {"root": root, "manifest": manifest, "result": result, "written": written}


def test_reproducibility_schema_is_closed_draft_2020_12() -> None:
    schema = _load_repro_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == REPRO_SCHEMA_ID
    assert schema["additionalProperties"] is False
    _assert_objects_closed(schema)
    required = set(schema["required"])
    assert required == set(REQUIRED_REPRO_FIELDS)
    properties = schema["properties"]
    assert properties["schema_version"]["const"] == REPRO_SCHEMA_ID
    assert properties["command"]["const"] == REPRODUCTION_ARGV
    assert set(schema["$defs"]["track_kind"]["enum"]) == set(TRACK_KINDS)
    assert set(schema["$defs"]["manifest_refs"]["required"]) == set(REQUIRED_MANIFEST_REFS)
    assert set(schema["$defs"]["metric"]["required"]) == set(REQUIRED_METRIC_FIELDS)
    assert set(schema["$defs"]["rights"]["required"]) == set(REQUIRED_RIGHTS_FIELDS)
    assert set(schema["$defs"]["inventory_entry"]["required"]) == set(REQUIRED_HASH_FIELDS)
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("track_kind", TRACK_KINDS)
def test_closed_manifest_accepts_separated_track_kinds(
    tmp_path: Path, track_kind: str
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / track_kind.lower(),
        track_kind=track_kind,
    )
    schema = _load_repro_schema()
    Draft202012Validator(schema).validate(bundle["manifest"])
    verified = verify_bundle(bundle["root"])
    assert verified["valid"] is True
    assert verified["schema_version"] == REPRO_SCHEMA_ID
    assert verified["track_kind"] == track_kind
    assert verified["publication"]["pbpp_headline_eligible"] is False
    assert verified["publication"]["independent_external_reproduction"] is False
    assert verified["headline_eligible"] is False


def test_development_reproduction_is_not_headline_or_repro_002(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "dev")
    verified = verify_bundle(bundle["root"])
    assert verified["track_kind"] == "DEVELOPMENT"
    assert verified["publication"] == {
        "certified": False,
        "headline": False,
        "independent": False,
        "independent_external_reproduction": False,
        "pbpp_headline_eligible": False,
        "publishable": False,
    }
    assert verified.get("repro_002") in {None, False, "open", "blocked"}
    readme = Path("eval/public/README.md").read_text(encoding="utf-8")
    assert "uv run --locked mneme eval-public --reproduce-bundle BUNDLE --out-dir DEST" in readme
    assert "REPRO-002" in readme
    assert "headline" in readme
    assert "independent" in readme
    assert "license" in readme
    assert "custody" in readme
    assert "operator" in readme
    assert "result-v1" in readme
    assert "result-v2" in readme
    assert "official" in readme
    assert "successor" in readme
    assert "development" in readme


def test_exact_digest_meanings_hash_named_file_bytes(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "digests")
    root = bundle["root"]
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    meanings = {
        "build_fingerprint": "build.json",
        "config_digest": "config.json",
        "bundle_digest": "bundle-manifest.json",
        "trace_index_digest": "traces.jsonl",
    }
    assert DIGEST_PAYLOAD_NAMES == meanings
    for field, name in meanings.items():
        raw = (root / name).read_bytes()
        assert result[field] == _sha256_ref(raw)
        mutated = bytearray(raw)
        mutated[0] ^= 0x01
        assert result[field] != _sha256_ref(bytes(mutated))
    manifest = bundle["manifest"]
    assert manifest["build"]["build_fingerprint"] == result["build_fingerprint"]
    assert manifest["config"]["config_digest"] == result["config_digest"]
    assert manifest["traces"]["trace_index_digest"] == result["trace_index_digest"]


def test_unknown_field_and_missing_declaration_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "unknown")
    root = bundle["root"]
    manifest = json.loads((root / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["unexpected"] = "field"
    _write_json(root / REPRO_MANIFEST_NAME, manifest)
    with pytest.raises(BundleError, match="unknown"):
        verify_bundle(root)

    missing = _write_reproducibility_bundle(tmp_path / "missing")
    payload = json.loads((missing["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    del payload["rights"]
    _write_json(missing["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="rights|missing"):
        verify_bundle(missing["root"])


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "official-without-fidelity",
            lambda manifest: manifest["manifests"].__setitem__("fidelity", None),
        ),
        (
            "successor-without-parent",
            lambda manifest: manifest["manifests"].__setitem__("parent", None),
        ),
        (
            "successor-without-difference",
            lambda manifest: manifest["manifests"].__setitem__("difference", None),
        ),
        (
            "development-marked-headline",
            lambda manifest: manifest["publication"].__setitem__("headline", True),
        ),
        (
            "blend-certified",
            lambda manifest: manifest["publication"].__setitem__("certified", True),
        ),
    ],
)
def test_track_kind_and_claim_boundaries_fail_closed(
    tmp_path: Path, label: str, mutate: Any
) -> None:
    track = (
        "OFFICIAL-UPSTREAM"
        if "official" in label
        else "ENHANCED-SUCCESSOR"
        if "successor" in label
        else "DEVELOPMENT"
    )
    bundle = _write_reproducibility_bundle(tmp_path / label, track_kind=track)
    manifest = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    mutate(manifest)
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, manifest)
    with pytest.raises(BundleError):
        verify_bundle(bundle["root"])


def test_one_byte_tamper_and_digest_mismatch_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "tamper")
    traces = bundle["root"] / "traces.jsonl"
    traces.write_bytes(traces.read_bytes()[:-1] + b"X")
    with pytest.raises(BundleError, match="digest|tamper|traces"):
        verify_bundle(bundle["root"])


def test_symlink_absolute_and_escaping_paths_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "paths")
    linked = bundle["root"] / "linked-traces.jsonl"
    linked.symlink_to(bundle["root"] / "traces.jsonl")
    manifest = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["hashes"].append(
        {
            "path": "linked-traces.jsonl",
            "size": 1,
            "media_type": "application/jsonl",
            "canonicalization": "raw-bytes",
            "sha256": _sha256_ref(b"x"),
        }
    )
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, manifest)
    with pytest.raises(BundleError, match="link|symlink"):
        verify_bundle(bundle["root"])

    escaping = _write_reproducibility_bundle(tmp_path / "escape")
    payload = json.loads((escaping["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["hashes"][0]["path"] = "../outside.json"
    _write_json(escaping["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="path"):
        verify_bundle(escaping["root"])

    absolute = _write_reproducibility_bundle(tmp_path / "absolute")
    payload = json.loads((absolute["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["hashes"][0]["path"] = "/tmp/absolute.json"
    _write_json(absolute["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="path"):
        verify_bundle(absolute["root"])


def test_secret_like_material_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "secret")
    leaked = bundle["root"] / "environment.json"
    env = json.loads(leaked.read_text(encoding="utf-8"))
    env["token"] = "sk_test_" + ("A" * 20)
    _write_json(leaked, env)
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(bundle["root"])


def test_non_finite_duplicate_and_deep_json_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "json")
    metrics = json.loads((bundle["root"] / "metrics.json").read_text(encoding="utf-8"))
    metrics["value"] = math.inf
    (bundle["root"] / "metrics.json").write_text(
        json.dumps(metrics, allow_nan=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BundleError, match="non-finite|invalid JSON"):
        verify_bundle(bundle["root"])

    duplicate = _write_reproducibility_bundle(tmp_path / "dup")
    (duplicate["root"] / REPRO_MANIFEST_NAME).write_text(
        '{"schema_version":"%s","schema_version":"%s"}\n' % (REPRO_SCHEMA_ID, REPRO_SCHEMA_ID),
        encoding="utf-8",
    )
    with pytest.raises(BundleError, match="duplicate"):
        verify_bundle(duplicate["root"])


def test_command_must_be_exact_argv(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "cmd",
        command=[
            "uv",
            "run",
            "--locked",
            "mneme",
            "eval-public",
            "--reproduce-bundle",
            "BUNDLE",
            "--out-dir",
            "OTHER",
        ],
    )
    with pytest.raises(BundleError, match="command"):
        verify_bundle(bundle["root"])


def test_missing_raw_traces_config_build_or_operator_fail_closed(tmp_path: Path) -> None:
    for name in ("traces.jsonl", "config.json", "build.json"):
        bundle = _write_reproducibility_bundle(tmp_path / f"missing-{name}")
        (bundle["root"] / name).unlink()
        with pytest.raises(BundleError):
            verify_bundle(bundle["root"])
    bundle = _write_reproducibility_bundle(tmp_path / "missing-operator")
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    del payload["operator"]
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="operator|missing"):
        verify_bundle(bundle["root"])


def test_unhashed_lock_named_file_is_scanned_and_rejected(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "lock-secret")
    leaked = bundle["root"] / "credentials.jsonl.lock"
    leaked.write_text("sk_test_" + ("B" * 20) + "\n", encoding="utf-8")
    with pytest.raises(BundleError, match="secret|inventory"):
        verify_bundle(bundle["root"])


def test_unhashed_lock_named_file_is_not_copied_on_reproduce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "lock-copy")
    monkeypatch.setattr(
        "eval.public.bundle._assert_reproduction_checkout", lambda _sha: None
    )
    extra = bundle["root"] / "sidecar.jsonl.lock"
    extra.write_text("not-a-secret\n", encoding="utf-8")
    destination = tmp_path / "lock-dest"
    with pytest.raises(BundleError, match="inventory"):
        reproduce_bundle(bundle["root"], destination)
    assert not destination.exists()
    assert not (destination / "sidecar.jsonl.lock").exists()


def test_manifest_metrics_must_match_recomputed_trace_metrics(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "metric-drift")
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["metrics"][0]["value"] = 0.0
    payload["metrics"][0]["numerator"] = 0
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="metrics"):
        verify_bundle(bundle["root"])


def test_missing_canonical_replay_artifact_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "no-replay")
    replay = bundle["root"] / "canonical-replay.json"
    replay.unlink()
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["hashes"] = [
        entry for entry in payload["hashes"] if entry["path"] != "canonical-replay.json"
    ]
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="replay"):
        verify_bundle(bundle["root"])


def test_null_custody_and_operator_values_fail_closed(tmp_path: Path) -> None:
    custody = _write_reproducibility_bundle(tmp_path / "null-custody")
    payload = json.loads((custody["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["custody"] = {"class": None, "declaration": None}
    _write_json(custody["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="custody"):
        verify_bundle(custody["root"])

    operator = _write_reproducibility_bundle(tmp_path / "null-operator")
    payload = json.loads((operator["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["operator"] = {
        "identity": "",
        "role": "auditor",
        "signer_role": "auditor",
        "disclosure_state": "disclosed",
    }
    _write_json(operator["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="operator"):
        verify_bundle(operator["root"])


def test_result_ledger_and_m15_cross_reference_mismatches_fail_closed(
    tmp_path: Path,
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "xref")
    result = json.loads((bundle["root"] / "result.json").read_text(encoding="utf-8"))
    result["build_fingerprint"] = f"sha256:{'9' * 64}"
    _write_json(bundle["root"] / "result.json", result)
    with pytest.raises(BundleError, match="digest|result"):
        verify_bundle(bundle["root"])

    replay_mismatch = _write_reproducibility_bundle(tmp_path / "replay")
    payload = json.loads(
        (replay_mismatch["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    payload["canonical_replay"]["digest"] = "0" * 64
    _write_json(replay_mismatch["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="replay|digest"):
        verify_bundle(replay_mismatch["root"])


def test_reproduce_deletes_incomplete_output_and_does_not_use_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "source")
    monkeypatch.setattr(
        "eval.public.bundle._assert_reproduction_checkout", lambda _sha: None
    )
    destination = tmp_path / "dest"
    reproduced = reproduce_bundle(bundle["root"], destination)
    assert reproduced["valid"] is True
    assert destination.is_dir()
    for name in ("result.json", "traces.jsonl", "bundle-manifest.json", REPRO_MANIFEST_NAME):
        assert (destination / name).read_bytes() == (bundle["root"] / name).read_bytes()
    dest_names = {path.name for path in destination.iterdir()}
    source_names = {path.name for path in bundle["root"].iterdir() if path.is_file()}
    assert dest_names <= source_names
    assert "metrics.json" in dest_names
    assert json.loads((destination / "metrics.json").read_text(encoding="utf-8")) == (
        json.loads((bundle["root"] / "metrics.json").read_text(encoding="utf-8"))
    )

    colliding = tmp_path / "collision"
    colliding.mkdir()
    (colliding / "stale.txt").write_text("stale\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        reproduce_bundle(bundle["root"], colliding)

    source = Path("eval/public/bundle.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "shell = True" not in source


def test_mutated_command_or_lock_fails_before_destination(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "lock")
    (bundle["root"] / "uv.lock").write_text("tampered-lock\n", encoding="utf-8")
    destination = tmp_path / "should-not-exist"
    with pytest.raises(BundleError):
        reproduce_bundle(bundle["root"], destination)
    assert not destination.exists()


def _clone_clean_checkout(tmp_path: Path) -> Path:
    clone = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", str(REPO_ROOT), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    leased = (
        Path("eval/public/schema/reproducibility-bundle-v1.schema.json"),
        Path("eval/public/bundle.py"),
        Path("eval/public/README.md"),
        Path("tests/test_public_reproducibility.py"),
    )
    copied = False
    for relative in leased:
        source = REPO_ROOT / relative
        if not source.is_file():
            continue
        target = clone / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copy2(source, target)
            copied = True
    if copied:
        subprocess.run(["git", "add", "--", *[str(path) for path in leased]], cwd=clone, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=repro-001",
                "-c",
                "user.email=repro-001@example.test",
                "commit",
                "-m",
                "repro-001 local checkout",
            ],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=clone, check=True, capture_output=True)
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert porcelain == ""
    return clone


def test_clean_checkout_runs_exact_documented_argv(tmp_path: Path) -> None:
    clone = _clone_clean_checkout(tmp_path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bundle = _write_reproducibility_bundle(tmp_path / "clean-source", run_commit=sha)
    destination = tmp_path / "clean-dest"
    env = {
        "HOME": str(tmp_path / "home"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.environ["PATH"],
        "TZ": "UTC",
        "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
        "UV_PROJECT_ENVIRONMENT": str(REPO_ROOT / ".venv"),
    }
    (tmp_path / "home").mkdir()
    command = [
        "uv",
        "run",
        "--locked",
        "mneme",
        "eval-public",
        "--reproduce-bundle",
        str(bundle["root"]),
        "--out-dir",
        str(destination),
    ]
    completed = subprocess.run(
        command,
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert destination.is_dir()
    assert (destination / "result.json").read_bytes() == (
        bundle["root"] / "result.json"
    ).read_bytes()


@pytest.mark.parametrize(
    "mutation",
    ("dirty", "wrong-commit", "command-token", "output-collision"),
)
def test_clean_checkout_denials_emit_no_partial_destination(
    tmp_path: Path, mutation: str
) -> None:
    clone = _clone_clean_checkout(tmp_path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if mutation == "wrong-commit":
        bundle = _write_reproducibility_bundle(
            tmp_path / "deny-source",
            run_commit="0" * 40,
        )
    else:
        bundle = _write_reproducibility_bundle(tmp_path / "deny-source", run_commit=sha)
    destination = tmp_path / "deny-dest"
    if mutation == "dirty":
        (clone / "extra-untracked.txt").write_text("dirty\n", encoding="utf-8")
    if mutation == "output-collision":
        destination.mkdir()
        (destination / "partial.json").write_text("{}\n", encoding="utf-8")
    command = [
        "uv",
        "run",
        "--locked",
        "mneme",
        "eval-public",
        "--reproduce-bundle",
        str(bundle["root"]),
        "--out-dir",
        str(destination),
    ]
    if mutation == "command-token":
        command[-1] = str(tmp_path / "other-dest")
        command.insert(-2, "--unexpected")
    env = {
        "HOME": str(tmp_path / "home"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.environ["PATH"],
        "TZ": "UTC",
        "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
        "UV_PROJECT_ENVIRONMENT": str(REPO_ROOT / ".venv"),
    }
    (tmp_path / "home").mkdir()
    completed = subprocess.run(
        command,
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    if mutation != "output-collision":
        assert not destination.exists()
    else:
        assert list(destination.iterdir()) == [destination / "partial.json"]
