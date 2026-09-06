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

from eval.harness.metrics import wilson_interval
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


def _path_with_invoking_uv() -> str:
    path = os.environ["PATH"]
    invoking_uv = os.environ.get("UV")
    if invoking_uv:
        return str(Path(invoking_uv).resolve().parent) + os.pathsep + path
    return path


def _invoking_uv_command() -> str:
    return os.environ.get("UV") or shutil.which("uv") or "uv"
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
_SMOKE_WILSON = wilson_interval(1, 1).as_dict()
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


def test_canonical_replay_digest_preserves_semantic_volatile_named_fields() -> None:
    payload = _canonical_replay_payload("wmbs-m01-development")
    changed = deepcopy(payload)
    payload["sut_outputs"] = {"signature": "accepted-result"}
    changed["sut_outputs"] = {"signature": "tampered-result"}

    assert canonical_replay_digest(payload) != canonical_replay_digest(changed)


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


def _m02_replay_payload(
    commit: str, *, system_seam: str = "public-cli-subprocess"
) -> dict[str, object]:
    payload = _canonical_replay_payload("wmbs-m01-development")
    fixture_digest = "2" * 64
    payload["suite"] = "wmbs-m02-retrieval-development"
    payload["seed_records"] = [20260801]
    payload["fixture"] = f"wmbs-m02-retrieval-development@sha256:{fixture_digest}"
    manifests = payload["manifests"]
    assert isinstance(manifests, dict)
    manifests["fixture_manifest_sha256"] = fixture_digest
    payload["build"] = {
        "candidate_git_sha": commit,
        "system_seam": system_seam,
    }
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
    identity = record["identity"]
    assert isinstance(identity, dict)
    identity["seed"] = 20260801
    run_profile = record["run_profile"]
    assert isinstance(run_profile, dict)
    run_profile["seeds"] = [20260801]
    record["metrics"] = [
        {
            "confidence_interval": {
                "high": _SMOKE_WILSON["ci_high"],
                "low": _SMOKE_WILSON["ci_low"],
            },
            "family": "retrieval",
            "name": "hit_at_k",
            "unit": "ratio",
            "value": _SMOKE_WILSON["point"],
        }
    ]
    assert validate_record(record) == []
    assert verify_result_digests(record, artifacts) == []
    return record


def _metric_record(*, version: str = "smoke-hit-at-k-v1") -> dict[str, object]:
    return {
        "family": "retrieval",
        "name": "hit_at_k",
        "version": version,
        "value": 1.0,
        "unit": "ratio",
        "numerator": 1,
        "denominator": 1,
        "sample_count": 1,
        "uncertainty_method": "wilson",
        "uncertainty_parameters": {"z": 1.96},
        "confidence_level": 0.95,
        "interval": {
            "low": _SMOKE_WILSON["ci_low"],
            "high": _SMOKE_WILSON["ci_high"],
        },
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
    k: int | None = 1,
    traces: bytes | None = None,
    scoring_profile: str = "smoke-hit-at-k-v1",
    suite: str = "smoke",
    system_seam: str = "public-cli-subprocess",
    lockfile: bytes | None = None,
    ledger_run_id: str | None = None,
    ledger_numeric_alias: bool = False,
    supersede_ledger: bool = False,
    trace_aborts: int = 0,
) -> dict[str, Any]:
    root.mkdir(parents=True)
    commit = run_commit or "0123456789abcdef0123456789abcdef01234567"
    traces = traces or (
        b'{"answer":"d1","gold_references":["d1"],"question_id":"q1",'
        b'"ranked_retrieved_hits":["d1"],"scoring_family":"deterministic-retrieval",'
        b'"stored_records":["d1"]}\n'
    )
    config = _canonical(
        {
            "family": "deterministic-retrieval",
            "interval_method": "wilson",
            "locale": "C",
            "scoring_profile": scoring_profile,
            "suite": suite,
            "timezone": "UTC",
            **({"k": k} if k is not None else {}),
        }
    )
    build = _canonical(
        {
            "candidate_git_sha": commit,
            "dirty": dirty,
            "environment_contract": "uv run --locked",
            "lockfile": "uv.lock",
            "system_seam": system_seam,
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
        "interval": {
            "confidence": 0.95,
            "high": _SMOKE_WILSON["ci_high"],
            "low": _SMOKE_WILSON["ci_low"],
            "method": "wilson",
        },
        "metric": "hit_at_k",
        "successes": 1,
        "total": 1,
        "trace_count": 1,
        "value": _SMOKE_WILSON["point"],
    }
    replay = _m02_replay_payload(commit, system_seam=system_seam)
    supporting = {
        "adapter.json": {"id": "smoke", "kind": "adapter"},
        "baseline.json": {"id": "none", "kind": "baseline"},
        "benchmark-ref.json": {"id": suite, "kind": "benchmark"},
        "dataset-split.json": {"id": "development-self-test", "kind": "dataset-split"},
        "fixture-ref.json": {"id": "smoke", "kind": "fixture"},
        "generator.json": {"id": "registry", "kind": "generator"},
        "judge-ref.json": {"id": None, "kind": "judge"},
        "model-ref.json": {"id": None, "kind": "model"},
        "prompt-ref.json": {"id": None, "kind": "prompt"},
        "reader-ref.json": {"id": None, "kind": "reader"},
        "scorer.json": {"id": scoring_profile, "kind": "scorer"},
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
    (root / "uv.lock").write_bytes(lockfile or (REPO_ROOT / "uv.lock").read_bytes())
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
    result["run_profile"]["aborts"] = trace_aborts
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
        ledger_result = deepcopy(result)
        if ledger_numeric_alias:
            ledger_metrics = ledger_result["metrics"]
            assert isinstance(ledger_metrics, list)
            assert isinstance(ledger_metrics[0], dict)
            ledger_metrics[0]["value"] = 1
        entry = append_entry(
            ledger_path,
            private_path,
            entry_id="repro-001-entry",
            timestamp="2026-09-05T00:00:00Z",
            entrant_id="synthetic-entrant",
            status="succeeded",
            run_id=ledger_run_id or str(result["identity"]["run_id"]),
            result=ledger_result,
            roster={"synthetic-entrant"},
        )
        if supersede_ledger:
            append_entry(
                ledger_path,
                private_path,
                entry_id="repro-001-supersession",
                timestamp="2026-09-05T00:01:00Z",
                entrant_id="synthetic-entrant",
                status="superseded",
                reason="result receipt withdrawn",
                supersedes="repro-001-entry",
                roster={"synthetic-entrant"},
            )
            replacement = deepcopy(result)
            replacement["record_id"] = "synthetic-v2-replacement-001"
            replacement["trace_id"] = "trace-replacement-001"
            replacement_identity = replacement["identity"]
            assert isinstance(replacement_identity, dict)
            replacement_identity["run_id"] = "run-replacement-001"
            replacement_identity["attempt_id"] = "attempt-replacement-001"
            append_entry(
                ledger_path,
                private_path,
                entry_id="repro-001-replacement",
                timestamp="2026-09-05T00:02:00Z",
                entrant_id="synthetic-entrant",
                status="succeeded",
                run_id="run-replacement-001",
                result=replacement,
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
    metric = _metric_record(version=scoring_profile)
    metric["aborted_count"] = trace_aborts
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
            "aborts": trace_aborts,
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
                "low": _SMOKE_WILSON["ci_low"],
                "high": _SMOKE_WILSON["ci_high"],
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
    assert "OPENAI_API_KEY" not in schema["$defs"]["environment"]["properties"][
        "allowlist"
    ]["items"]["enum"]
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
    assert "Set `UV_OFFLINE=1`" in readme
    assert "overall command as offline" in readme
    assert "official" in readme
    assert "successor" in readme
    assert "development" in readme
    assert "active and unsuperseded" in readme
    assert "exact named file and semantic role" in readme
    assert "does not scrub the parent process environment" in readme
    assert "source revision equal to the bound build commit" in readme


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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [("digest", "digest"), ("boolean-version", "inventory")],
)
def test_nested_bundle_manifest_inventory_is_semantically_verified(
    tmp_path: Path, mutation: str, message: str
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "nested-manifest", include_ledger=False
    )
    root = bundle["root"]
    nested_path = root / "bundle-manifest.json"
    nested = json.loads(nested_path.read_text(encoding="utf-8"))
    if mutation == "digest":
        nested["files"]["adapter.json"] = "9" * 64
    else:
        nested["version"] = True
    nested_bytes = _write_json(nested_path, nested)

    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["bundle_digest"] = _sha256_ref(nested_bytes)
    result_bytes = _write_json(result_path, result)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    for name, payload in (
        ("bundle-manifest.json", nested_bytes),
        ("result.json", result_bytes),
    ):
        entry = next(item for item in manifest["hashes"] if item["path"] == name)
        entry["size"] = len(payload)
        entry["sha256"] = _sha256_ref(payload)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match=f"bound bundle manifest {message}"):
        verify_bundle(root)


def test_unknown_field_and_missing_declaration_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "unknown")
    root = bundle["root"]
    manifest = json.loads((root / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["unexpected"] = "field"
    _write_json(root / REPRO_MANIFEST_NAME, manifest)
    with pytest.raises(BundleError, match="unknown|schema"):
        verify_bundle(root)

    missing = _write_reproducibility_bundle(tmp_path / "missing")
    payload = json.loads((missing["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    del payload["rights"]
    _write_json(missing["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="rights|missing"):
        verify_bundle(missing["root"])


def test_rights_source_revision_must_match_bound_build(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "rights-revision")
    root = bundle["root"]
    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rights"]["source_revision"] = "f" * 40
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="rights source revision"):
        verify_bundle(root)


def test_reproducibility_toolchain_is_exactly_uv(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "wrong-toolchain")
    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["build"]["toolchain"] = "pip"
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="toolchain|schema"):
        verify_bundle(bundle["root"])


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


@pytest.mark.parametrize(
    ("track_kind", "lineage_path"),
    [
        ("OFFICIAL-UPSTREAM", ("fidelity", "dataset_digest")),
        ("ENHANCED-SUCCESSOR", ("parent_construct_digest",)),
    ],
)
def test_result_lineage_must_match_authenticated_manifest(
    tmp_path: Path, track_kind: str, lineage_path: tuple[str, ...]
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / track_kind.lower(),
        track_kind=track_kind,
    )
    root = bundle["root"]
    manifest = json.loads((root / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    lineage = manifest["lineage"]
    for key in lineage_path[:-1]:
        lineage = lineage[key]
    lineage[lineage_path[-1]] = "sha256:" + "9" * 64
    _write_json(root / REPRO_MANIFEST_NAME, manifest)

    with pytest.raises(BundleError, match="result lineage does not match manifest"):
        verify_bundle(root)


@pytest.mark.parametrize(
    ("track_kind", "artifact_name", "field", "replacement", "message"),
    [
        (
            "OFFICIAL-UPSTREAM",
            "fidelity.json",
            "upstream_protocol_digest",
            "sha256:" + "9" * 64,
            "fidelity artifact",
        ),
        (
            "OFFICIAL-UPSTREAM",
            "fidelity.json",
            "dataset_digest",
            "sha256:" + "9" * 64,
            "fidelity artifact",
        ),
        (
            "ENHANCED-SUCCESSOR",
            "parent.json",
            "record_id",
            "different-official-record",
            "parent artifact",
        ),
    ],
)
def test_lineage_artifacts_must_match_result_lineage(
    tmp_path: Path,
    track_kind: str,
    artifact_name: str,
    field: str,
    replacement: str,
    message: str,
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / track_kind.lower(), track_kind=track_kind
    )
    root = bundle["root"]
    artifact_path = root / artifact_name
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact[field] = replacement
    artifact_bytes = _write_json(artifact_path, artifact)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ref_name = artifact_name.removesuffix(".json")
    manifest["manifests"][ref_name] = _named_ref(ref_name, artifact_bytes)
    entry = next(item for item in manifest["hashes"] if item["path"] == artifact_name)
    entry["size"] = len(artifact_bytes)
    entry["sha256"] = _sha256_ref(artifact_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match=f"{message}.*result lineage"):
        verify_bundle(root)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("seeds", [20260802]),
        ("retries", 1),
        ("aborts", 1),
    ],
)
def test_result_run_profile_must_match_trace_custody(
    tmp_path: Path, field: str, replacement: object
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / f"run-profile-{field}", include_ledger=False
    )
    root = bundle["root"]
    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["run_profile"][field] = replacement
    if field == "seeds":
        result["identity"]["seed"] = replacement[0]
    result_bytes = _write_json(result_path, result)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    entry = next(item for item in manifest["hashes"] if item["path"] == "result.json")
    entry["size"] = len(result_bytes)
    entry["sha256"] = _sha256_ref(result_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="run profile does not match trace custody"):
        verify_bundle(root)


def test_one_byte_tamper_and_digest_mismatch_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "tamper")
    traces = bundle["root"] / "traces.jsonl"
    traces.write_bytes(traces.read_bytes()[:-1] + b"X")
    with pytest.raises(BundleError, match="digest|tamper|traces"):
        verify_bundle(bundle["root"])


def test_symlink_absolute_and_escaping_paths_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "paths")
    linked = bundle["root"] / "linked-traces.jsonl"
    try:
        linked.symlink_to(bundle["root"] / "traces.jsonl")
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
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
    with pytest.raises(BundleError, match="path|schema"):
        verify_bundle(escaping["root"])

    absolute = _write_reproducibility_bundle(tmp_path / "absolute")
    payload = json.loads((absolute["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["hashes"][0]["path"] = "/tmp/absolute.json"
    _write_json(absolute["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="path|schema"):
        verify_bundle(absolute["root"])


def test_symlinked_bundle_ancestor_fails_closed(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    bundle = _write_reproducibility_bundle(real_parent / "bundle")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    with pytest.raises(BundleError, match="links or junctions"):
        verify_bundle(alias / bundle["root"].name)
    with pytest.raises(BundleError, match="links or junctions"):
        reproduce_bundle(bundle["root"], alias / "destination")


def test_secret_like_material_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "secret")
    leaked = bundle["root"] / "environment.json"
    env = json.loads(leaked.read_text(encoding="utf-8"))
    env["token"] = "sk_test_" + ("A" * 20)
    _write_json(leaked, env)
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize(
    "secret",
    (
        "github_" + "pat_" + ("A" * 24),
        "glpat-" + ("B" * 24),
        "xoxb-" + ("1" * 24),
        "AKIA" + ("C" * 16),
        "Bearer " + ("d" * 24),
        "https://user:password@example.invalid/resource",
    ),
)
def test_common_credential_families_fail_closed(tmp_path: Path, secret: str) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / hashlib.sha256(secret.encode()).hexdigest())
    leaked = bundle["root"] / "environment.json"
    env = json.loads(leaked.read_text(encoding="utf-8"))
    env["credential"] = secret
    _write_json(leaked, env)
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize("location", ("artifact-value", "artifact-key", "manifest"))
def test_json_escaped_credentials_fail_closed(tmp_path: Path, location: str) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / f"escaped-{location}")
    root = bundle["root"]
    if location == "manifest":
        path = root / REPRO_MANIFEST_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["operator"]["identity"] = "github_pat_" + ("M" * 24)
    else:
        path = root / "environment.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        secret = "github_pat_" + ("E" * 24)
        if location == "artifact-key":
            payload[secret] = "value"
        else:
            payload["credential"] = secret
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    encoded = encoded.replace("github_pat_", r"github\u005fpat_")
    assert "github_pat_" not in encoded
    path.write_text(encoded, encoding="utf-8", newline="\n")
    with pytest.raises(BundleError, match="decoded artifact"):
        verify_bundle(root)


def test_aggregate_bundle_size_is_bounded_before_full_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "aggregate-bound")
    total_size = sum(path.stat().st_size for path in bundle["root"].iterdir())
    monkeypatch.setattr(public_bundle, "_MAX_REPRO_BUNDLE_BYTES", total_size - 1)
    with pytest.raises(BundleError, match="aggregate size bound"):
        verify_bundle(bundle["root"])


def test_bundle_file_count_is_bounded_during_inventory_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "file-count-bound")
    count = sum(1 for _ in bundle["root"].iterdir())
    monkeypatch.setattr(public_bundle, "_MAX_REPRO_FILES", count - 1)
    with pytest.raises(BundleError, match="file-count bound"):
        verify_bundle(bundle["root"])


def test_inventory_json_depth_is_bounded(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "artifact-depth")
    nested: object = "leaf"
    for _ in range(70):
        nested = {"nested": nested}
    artifact = bundle["root"] / "adapter.json"
    artifact_bytes = _write_json(artifact, nested)
    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifests"]["adapter"] = _named_ref("adapter", artifact_bytes)
    entry = next(item for item in manifest["hashes"] if item["path"] == "adapter.json")
    entry["size"] = len(artifact_bytes)
    entry["sha256"] = _sha256_ref(artifact_bytes)
    _write_json(manifest_path, manifest)
    with pytest.raises(BundleError, match="nesting"):
        verify_bundle(bundle["root"])


def test_inventory_media_type_matches_core_artifact_content(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "media-type")
    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["hashes"] if item["path"] == "adapter.json")
    entry["media_type"] = "text/plain"
    _write_json(manifest_path, manifest)
    with pytest.raises(BundleError, match="media type"):
        verify_bundle(bundle["root"])


def test_hardlinked_inventory_artifact_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "hardlink")
    artifact = bundle["root"] / "result.json"
    external = tmp_path / "external-result.json"
    external.write_bytes(artifact.read_bytes())
    artifact.unlink()
    os.link(external, artifact)
    with pytest.raises(BundleError, match="hardlink"):
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
    with pytest.raises(BundleError, match="command|schema"):
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
    with pytest.raises(BundleError, match="operator|missing|schema"):
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
        "eval.public.bundle._assert_reproduction_checkout", lambda _sha, _lock: None
    )
    extra = bundle["root"] / "sidecar.jsonl.lock"
    extra.write_text("not-a-secret\n", encoding="utf-8")
    destination = tmp_path / "lock-dest"
    with pytest.raises(BundleError, match="inventory"):
        reproduce_bundle(bundle["root"], destination)
    assert not destination.exists()
    assert not (destination / "sidecar.jsonl.lock").exists()


def test_schema_constraints_are_enforced_not_just_file_presence(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "schema-bypass")
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["metrics"][0]["family"] = "unknown"
    payload["metrics"][0]["uncertainty_parameters"]["extra"] = True
    payload["metrics"][0]["sample_count"] = 1.0
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="schema"):
        verify_bundle(bundle["root"])


def test_listed_sibling_lock_file_fails_inventory(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "listed-lock")
    (bundle["root"] / "traces.jsonl.lock").write_text("not-a-secret\n", encoding="utf-8")
    with pytest.raises(BundleError, match="inventory"):
        verify_bundle(bundle["root"])


def test_fabricated_ledger_and_manifest_refs_fail_closed(tmp_path: Path) -> None:
    ledger = _write_reproducibility_bundle(tmp_path / "fake-ledger")
    payload = json.loads((ledger["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["ledger_ref"] = _named_ref("ledger-entry", b"fabricated-ledger")
    _write_json(ledger["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="ledger"):
        verify_bundle(ledger["root"])

    adapter = _write_reproducibility_bundle(tmp_path / "fake-adapter")
    payload = json.loads((adapter["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["manifests"]["adapter"] = _named_ref("adapter", b"fabricated-adapter")
    _write_json(adapter["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="adapter"):
        verify_bundle(adapter["root"])


def test_signed_ledger_run_id_must_match_result_identity(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "ledger-run-mismatch", ledger_run_id="different-run"
    )
    with pytest.raises(BundleError, match="ledger run_id does not match"):
        verify_bundle(bundle["root"])


def test_signed_ledger_result_requires_canonical_type_exact_match(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "ledger-numeric-alias", ledger_numeric_alias=True
    )

    with pytest.raises(BundleError, match="ledger result reference mismatch"):
        verify_bundle(bundle["root"])


def test_signed_ledger_requires_canonical_result_artifact_bytes(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "noncanonical-result")
    root = bundle["root"]
    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result_bytes = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    result_path.write_bytes(result_bytes)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    entry = next(
        item for item in manifest["hashes"] if item["path"] == "result.json"
    )
    entry["size"] = len(result_bytes)
    entry["sha256"] = _sha256_ref(result_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="result.json bytes must be canonical"):
        verify_bundle(root)


def test_superseded_ledger_entry_cannot_supply_inclusion_receipt(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "superseded-ledger", supersede_ledger=True
    )
    with pytest.raises(BundleError, match="inclusion receipt is superseded"):
        verify_bundle(bundle["root"])


def test_manifest_ref_cannot_bind_a_different_inventory_artifact(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "cross-bound-adapter")
    root = bundle["root"]
    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scorer_bytes = (root / "scorer.json").read_bytes()
    manifest["manifests"]["adapter"] = _named_ref("adapter", scorer_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="adapter.*named artifact"):
        verify_bundle(root)


@pytest.mark.parametrize(
    ("artifact_name", "field", "replacement", "message"),
    [
        ("adapter.json", "kind", "scorer", "adapter artifact kind"),
        ("scorer.json", "id", "different-profile", "scorer artifact"),
        ("benchmark-ref.json", "id", "different-suite", "benchmark artifact"),
    ],
)
def test_manifest_artifact_semantics_match_their_declared_roles(
    tmp_path: Path,
    artifact_name: str,
    field: str,
    replacement: str,
    message: str,
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / artifact_name)
    root = bundle["root"]
    artifact_path = root / artifact_name
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact[field] = replacement
    artifact_bytes = _write_json(artifact_path, artifact)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ref_key = {
        "adapter.json": "adapter",
        "benchmark-ref.json": "benchmark",
        "scorer.json": "scorer",
    }[artifact_name]
    ref_name = "benchmark" if ref_key == "benchmark" else ref_key
    manifest["manifests"][ref_key] = _named_ref(ref_name, artifact_bytes)
    entry = next(item for item in manifest["hashes"] if item["path"] == artifact_name)
    entry["size"] = len(artifact_bytes)
    entry["sha256"] = _sha256_ref(artifact_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match=message):
        verify_bundle(root)


def test_unreferenced_named_manifest_artifact_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "unreferenced-fidelity", include_ledger=False
    )
    root = bundle["root"]
    fidelity_bytes = _write_json(
        root / "fidelity.json",
        {"kind": "fidelity", "upstream_protocol_digest": "sha256:" + "c" * 64},
    )

    nested_path = root / "bundle-manifest.json"
    nested = json.loads(nested_path.read_text(encoding="utf-8"))
    nested["files"]["fidelity.json"] = _sha256_hex(fidelity_bytes)
    nested_bytes = _write_json(nested_path, nested)

    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["bundle_digest"] = _sha256_ref(nested_bytes)
    result_bytes = _write_json(result_path, result)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    manifest["hashes"].append(
        {
            "canonicalization": "raw-bytes",
            "media_type": "application/json",
            "path": "fidelity.json",
            "sha256": _sha256_ref(fidelity_bytes),
            "size": len(fidelity_bytes),
        }
    )
    manifest["hashes"].sort(key=lambda item: item["path"])
    for name, payload in (
        ("bundle-manifest.json", nested_bytes),
        ("result.json", result_bytes),
    ):
        entry = next(item for item in manifest["hashes"] if item["path"] == name)
        entry["size"] = len(payload)
        entry["sha256"] = _sha256_ref(payload)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="unreferenced fidelity artifact"):
        verify_bundle(root)


@pytest.mark.parametrize(
    ("name", "media_type", "artifact", "message"),
    (
        ("payload.bin", "application/octet-stream", b"opaque\x00\xff", "media type"),
        (
            "official-proof.json",
            "application/json",
            b'{"claim":"official"}\n',
            "unexpected artifact",
        ),
    ),
)
def test_unrecognized_inventory_artifact_fails_closed(
    tmp_path: Path, name: str, media_type: str, artifact: bytes, message: str
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "unrecognized-artifact", include_ledger=False
    )
    root = bundle["root"]
    (root / name).write_bytes(artifact)

    nested_path = root / "bundle-manifest.json"
    nested = json.loads(nested_path.read_text(encoding="utf-8"))
    nested["files"][name] = _sha256_hex(artifact)
    nested_bytes = _write_json(nested_path, nested)

    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["bundle_digest"] = _sha256_ref(nested_bytes)
    result_bytes = _write_json(result_path, result)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    manifest["hashes"].append(
        {
            "canonicalization": "raw-bytes",
            "media_type": media_type,
            "path": name,
            "sha256": _sha256_ref(artifact),
            "size": len(artifact),
        }
    )
    manifest["hashes"].sort(key=lambda item: item["path"])
    for name, payload in (
        ("bundle-manifest.json", nested_bytes),
        ("result.json", result_bytes),
    ):
        entry = next(item for item in manifest["hashes"] if item["path"] == name)
        entry["size"] = len(payload)
        entry["sha256"] = _sha256_ref(payload)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match=message):
        verify_bundle(root)


def test_ledger_verification_uses_inventory_bound_private_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "ledger-snapshot")
    root = bundle["root"]
    expected_ledger = (root / "ledger.jsonl").read_bytes()
    observed: list[Path] = []

    def observe_snapshot(ledger_path: Path, public_key_path: Path) -> list[dict[str, object]]:
        ledger_path = Path(ledger_path)
        public_key_path = Path(public_key_path)
        observed.append(ledger_path.parent)
        assert ledger_path.parent != root
        assert public_key_path.parent == ledger_path.parent
        assert ledger_path.read_bytes() == expected_ledger
        return verify_ledger(ledger_path, public_key_path)

    monkeypatch.setattr("leaderboard.ledger.verify_ledger", observe_snapshot)
    assert verify_bundle(root)["valid"] is True
    assert len(observed) == 1
    assert not observed[0].exists()
    assert not (root / "ledger.jsonl.lock").exists()


def test_semantic_verification_uses_inventory_bound_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "semantic-snapshot")
    root = bundle["root"]
    original_inventory = public_bundle._inventory_bytes

    def mutate_after_snapshot(
        inventory_root: Path,
        manifest: dict[str, Any],
        *,
        manifest_bytes: bytes | None = None,
    ) -> dict[str, bytes]:
        payloads = original_inventory(
            inventory_root, manifest, manifest_bytes=manifest_bytes
        )
        (inventory_root / "result.json").write_text("{}\n", encoding="utf-8")
        (inventory_root / "canonical-replay.json").write_text("{}\n", encoding="utf-8")
        (inventory_root / "config.json").write_text("{}\n", encoding="utf-8")
        (inventory_root / "metrics.json").write_text("{}\n", encoding="utf-8")
        return payloads

    monkeypatch.setattr(public_bundle, "_inventory_bytes", mutate_after_snapshot)
    assert verify_bundle(root)["valid"] is True


def test_manifest_schema_and_inventory_share_one_inode_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "manifest-snapshot")
    root = bundle["root"]
    original_inventory = public_bundle._inventory_bytes

    def replace_manifest_after_validation(
        inventory_root: Path,
        manifest: dict[str, Any],
        *,
        manifest_bytes: bytes | None = None,
    ) -> dict[str, bytes]:
        assert manifest_bytes is not None
        (inventory_root / REPRO_MANIFEST_NAME).write_text("{}\n", encoding="utf-8")
        return original_inventory(
            inventory_root, manifest, manifest_bytes=manifest_bytes
        )

    monkeypatch.setattr(
        public_bundle, "_inventory_bytes", replace_manifest_after_validation
    )
    assert verify_bundle(root)["valid"] is True


def test_manifest_bytes_and_inventory_order_are_canonical(tmp_path: Path) -> None:
    pretty = _write_reproducibility_bundle(tmp_path / "pretty-manifest")
    pretty_path = pretty["root"] / REPRO_MANIFEST_NAME
    payload = json.loads(pretty_path.read_text(encoding="utf-8"))
    pretty_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(BundleError, match="manifest bytes must be canonical"):
        verify_bundle(pretty["root"])

    unordered = _write_reproducibility_bundle(tmp_path / "unordered-inventory")
    unordered_path = unordered["root"] / REPRO_MANIFEST_NAME
    payload = json.loads(unordered_path.read_text(encoding="utf-8"))
    payload["hashes"] = list(reversed(payload["hashes"]))
    _write_json(unordered_path, payload)
    with pytest.raises(BundleError, match="canonical sorted order"):
        verify_bundle(unordered["root"])


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    (
        ("build", "toolchain", "pip"),
        ("environment", "runtime", "cpython-3.13"),
        ("environment", "platform", "windows"),
    ),
)
def test_manifest_runtime_declarations_match_inventory_artifacts(
    tmp_path: Path, section: str, field: str, replacement: object
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / f"declaration-{section}-{field}"
    )
    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[section][field] = replacement
    _write_json(manifest_path, manifest)
    with pytest.raises(BundleError, match="declaration does not match|schema"):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize("artifact_name", ["config.json", "build.json", "environment.json"])
def test_runtime_artifacts_reject_undeclared_fields(
    tmp_path: Path, artifact_name: str
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / f"closed-{artifact_name}")
    root = bundle["root"]
    artifact_path = root / artifact_name
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["headline_eligible"] = True
    artifact_bytes = _write_json(artifact_path, artifact)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["hashes"] if item["path"] == artifact_name)
    entry["size"] = len(artifact_bytes)
    entry["sha256"] = _sha256_ref(artifact_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="declaration does not match"):
        verify_bundle(root)


def test_build_artifact_boolean_version_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "boolean-build-version")
    root = bundle["root"]
    build_path = root / "build.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["version"] = True
    build_bytes = _write_json(build_path, build)
    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["hashes"] if item["path"] == "build.json")
    entry["size"] = len(build_bytes)
    entry["sha256"] = _sha256_ref(build_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="build declaration"):
        verify_bundle(root)


def test_environment_allowlist_rejects_credential_variables(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "credential-environment")
    root = bundle["root"]
    environment_path = root / "environment.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    environment["allowlist"].append("OPENAI_API_KEY")
    environment["allowlist"].sort()
    environment_bytes = _write_json(environment_path, environment)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["environment"]["allowlist"] = environment["allowlist"]
    entry = next(
        item for item in manifest["hashes"] if item["path"] == "environment.json"
    )
    entry["size"] = len(environment_bytes)
    entry["sha256"] = _sha256_ref(environment_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="allowlist|schema"):
        verify_bundle(root)


def test_reproduction_uses_one_inventory_bound_source_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "reproduction-snapshot")
    root = bundle["root"]
    expected_result = (root / "result.json").read_bytes()
    original_inventory = public_bundle._inventory_bytes

    def mutate_source_after_snapshot(
        inventory_root: Path,
        manifest: dict[str, Any],
        *,
        manifest_bytes: bytes | None = None,
    ) -> dict[str, bytes]:
        payloads = original_inventory(
            inventory_root, manifest, manifest_bytes=manifest_bytes
        )
        if inventory_root == root:
            (root / "result.json").write_text("{}\n", encoding="utf-8")
        return payloads

    monkeypatch.setattr(public_bundle, "_inventory_bytes", mutate_source_after_snapshot)
    monkeypatch.setattr(
        public_bundle, "_assert_reproduction_checkout", lambda _sha, _lock: None
    )
    destination = tmp_path / "reproduction-destination"
    assert reproduce_bundle(root, destination)["valid"] is True
    assert (destination / "result.json").read_bytes() == expected_result
    assert verify_bundle(destination)["valid"] is True


def test_reproduce_cleanup_does_not_delete_foreign_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "foreign-source")
    monkeypatch.setattr(
        "eval.public.bundle._assert_reproduction_checkout", lambda _sha, _lock: None
    )
    destination = tmp_path / "foreign-dest"

    def collide(_source: Path, target: Path) -> None:
        target_path = Path(target)
        if target_path == destination:
            destination.mkdir()
            (destination / "marker.txt").write_text("keep\n", encoding="utf-8")
            raise OSError("simulated rename collision")
        raise AssertionError(f"unexpected publication target: {target_path}")

    monkeypatch.setattr(public_bundle, "_publish_directory_noreplace", collide)
    with pytest.raises(OSError, match="rename collision"):
        reproduce_bundle(bundle["root"], destination)
    assert destination.is_dir()
    assert (destination / "marker.txt").read_text(encoding="utf-8") == "keep\n"


def test_atomic_publication_never_replaces_existing_destination(tmp_path: Path) -> None:
    from eval.public.bundle import _publish_directory_noreplace

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "new.txt").write_text("new\n", encoding="utf-8")
    (destination / "marker.txt").write_text("keep\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        _publish_directory_noreplace(source, destination)
    assert (destination / "marker.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (destination / "new.txt").exists()
    assert (source / "new.txt").is_file()


def test_manifest_metrics_must_match_recomputed_trace_metrics(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "metric-drift")
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["metrics"][0]["value"] = 0.0
    payload["metrics"][0]["numerator"] = 0
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="metrics"):
        verify_bundle(bundle["root"])


def test_trace_aborts_are_disclosed_in_result_and_manifest_metrics(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "disclosed-abort", trace_aborts=1
    )
    verified = verify_bundle(bundle["root"])
    assert verified["valid"] is True
    assert bundle["result"]["run_profile"]["aborts"] == 1
    assert bundle["manifest"]["metrics"][0]["aborted_count"] == 1

    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metrics"][0]["aborted_count"] = 0
    _write_json(manifest_path, manifest)
    with pytest.raises(BundleError, match="metrics"):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize("location", ["top-level", "interval"])
def test_metrics_artifact_rejects_undeclared_fields(
    tmp_path: Path, location: str
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / f"metrics-extra-{location}")
    root = bundle["root"]
    metrics_path = root / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    target = metrics if location == "top-level" else metrics["interval"]
    target["headline_eligible"] = True
    metrics_bytes = _write_json(metrics_path, metrics)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["hashes"] if item["path"] == "metrics.json")
    entry["size"] = len(metrics_bytes)
    entry["sha256"] = _sha256_ref(metrics_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="metrics|intervals"):
        verify_bundle(root)


def test_metrics_artifact_rejects_boolean_count_alias(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "boolean-metric-count")
    root = bundle["root"]
    metrics_path = root / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["successes"] = True
    metrics_bytes = _write_json(metrics_path, metrics)
    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["hashes"] if item["path"] == "metrics.json")
    entry["size"] = len(metrics_bytes)
    entry["sha256"] = _sha256_ref(metrics_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="metrics do not recompute"):
        verify_bundle(root)


def test_result_metrics_must_match_recomputed_trace_metrics(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "result-metric-drift", include_ledger=False
    )
    root = bundle["root"]
    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["metrics"][0]["value"] = 0.0
    result_bytes = _write_json(result_path, result)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    entry = next(item for item in manifest["hashes"] if item["path"] == "result.json")
    entry["size"] = len(result_bytes)
    entry["sha256"] = _sha256_ref(result_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="result metrics do not match"):
        verify_bundle(root)


def test_manifest_metrics_require_canonical_numeric_types(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "manifest-metric-alias")
    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metrics"][0]["value"] = 1
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="metrics do not recompute"):
        verify_bundle(bundle["root"])


def test_result_metrics_require_canonical_numeric_types(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "result-metric-alias", include_ledger=False
    )
    root = bundle["root"]
    result_path = root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["metrics"][0]["value"] = 1
    result_bytes = _write_json(result_path, result)

    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_ref"] = _named_ref("result-v2", result_bytes)
    entry = next(item for item in manifest["hashes"] if item["path"] == "result.json")
    entry["size"] = len(result_bytes)
    entry["sha256"] = _sha256_ref(result_bytes)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="result metrics do not match"):
        verify_bundle(root)


def _rewrite_metrics_and_manifest(
    root: Path,
    *,
    value: float,
    low: float,
    high: float,
) -> None:
    metrics_path = root / "metrics.json"
    measured = json.loads(metrics_path.read_text(encoding="utf-8"))
    measured["value"] = value
    measured["interval"]["low"] = low
    measured["interval"]["high"] = high
    metrics_bytes = _write_json(metrics_path, measured)
    payload = json.loads((root / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["metrics"][0]["value"] = value
    payload["metrics"][0]["interval"] = {"low": low, "high": high}
    payload["intervals"][0]["low"] = low
    payload["intervals"][0]["high"] = high
    for entry in payload["hashes"]:
        if entry["path"] == "metrics.json":
            entry["size"] = len(metrics_bytes)
            entry["sha256"] = _sha256_ref(metrics_bytes)
    _write_json(root / REPRO_MANIFEST_NAME, payload)


def test_later_manifest_metrics_and_intervals_must_recompute(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "later-metrics")
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    extra = _metric_record()
    extra["name"] = "fabricated_recall"
    extra["value"] = 0.0
    extra["numerator"] = 0
    extra["interval"] = {"low": 0.0, "high": 0.1}
    payload["metrics"].append(extra)
    payload["intervals"].append(
        {
            "metric": "fabricated_recall",
            "method": "wilson",
            "confidence_level": 0.95,
            "low": 0.0,
            "high": 0.1,
        }
    )
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="metrics|intervals"):
        verify_bundle(bundle["root"])


def test_fabricated_score_matching_metrics_and_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "fake-score")
    _rewrite_metrics_and_manifest(bundle["root"], value=0.0, low=0.2, high=1.0)
    with pytest.raises(BundleError, match="metrics"):
        verify_bundle(bundle["root"])


def test_fabricated_confidence_interval_matching_metrics_and_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "fake-ci")
    _rewrite_metrics_and_manifest(bundle["root"], value=1.0, low=0.0, high=0.1)
    with pytest.raises(BundleError, match="metrics|intervals"):
        verify_bundle(bundle["root"])


def test_hit_at_k_scores_only_the_bound_prefix(tmp_path: Path) -> None:
    traces = (
        b'{"answer":"d1","gold_references":["d2"],"question_id":"q1",'
        b'"ranked_retrieved_hits":["d1","d2"],"scoring_family":"deterministic-retrieval",'
        b'"stored_records":["d1","d2"]}\n'
    )
    bundle = _write_reproducibility_bundle(tmp_path / "topk", traces=traces)
    with pytest.raises(BundleError, match="metrics"):
        verify_bundle(bundle["root"])


def test_schema_valid_metric_metadata_mismatch_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "meta")
    payload = json.loads((bundle["root"] / REPRO_MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["metrics"][0]["family"] = "performance"
    payload["metrics"][0]["unit"] = "milliseconds"
    payload["metrics"][0]["uncertainty_method"] = "bootstrap"
    payload["metrics"][0]["confidence_level"] = 0.9
    payload["metrics"][0]["exclusions"] = ["late"]
    payload["metrics"][0]["failed_count"] = 1
    _write_json(bundle["root"] / REPRO_MANIFEST_NAME, payload)
    with pytest.raises(BundleError, match="metrics"):
        verify_bundle(bundle["root"])


def test_reproduce_reruns_scorer_and_fails_closed_without_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "no-k", k=None)
    monkeypatch.setattr(
        "eval.public.bundle._assert_reproduction_checkout", lambda _sha, _lock: None
    )
    destination = tmp_path / "no-k-dest"
    with pytest.raises(BundleError, match="k"):
        reproduce_bundle(bundle["root"], destination)
    assert not destination.exists()


def test_unregistered_scoring_profile_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "unknown-profile",
        scoring_profile="unregistered-hit-at-k-v9",
    )
    with pytest.raises(BundleError, match="scoring profile"):
        verify_bundle(bundle["root"])


def test_blank_bound_suite_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "blank-suite", suite=" ")

    with pytest.raises(BundleError, match="suite"):
        verify_bundle(bundle["root"])


def test_blank_build_system_seam_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / "blank-system-seam", system_seam=" "
    )

    with pytest.raises(BundleError, match="system seam"):
        verify_bundle(bundle["root"])


def test_duplicate_ranked_retrieved_ids_fail_closed(tmp_path: Path) -> None:
    traces = (
        b'{"answer":"d1","gold_references":["d1"],"question_id":"q1",'
        b'"ranked_retrieved_hits":["d1","d1"],"scoring_family":"deterministic-retrieval",'
        b'"stored_records":["d1"]}\n'
    )
    bundle = _write_reproducibility_bundle(tmp_path / "dup-ranks", traces=traces)
    with pytest.raises(BundleError, match="duplicate|ranked"):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize(
    ("traces", "message"),
    [
        (
            b'{"answer":"d1","gold_references":["d1"],"question_id":"q1",'
            b'"ranked_retrieved_hits":["d1"],"scoring_family":"other",'
            b'"stored_records":["d1"]}\n',
            "scoring family",
        ),
        (
            b'{"answer":"d1","gold_references":[["d1"]],"question_id":"q1",'
            b'"ranked_retrieved_hits":["d1"],'
            b'"scoring_family":"deterministic-retrieval",'
            b'"stored_records":["d1"]}\n',
            "identifiers are malformed",
        ),
        (
            b'{"answer":" ","gold_references":[" "],"question_id":"q1",'
            b'"ranked_retrieved_hits":[" "],'
            b'"scoring_family":"deterministic-retrieval",'
            b'"stored_records":[" "]}\n',
            "identifiers are malformed",
        ),
        (
            b'{"answer":"d1","gold_references":["d1"],"question_id":"q1",'
            b'"ranked_retrieved_hits":["d1"],'
            b'"scoring_family":"deterministic-retrieval",'
            b'"stored_records":["d1"]}\n'
            b'{"answer":"d1","gold_references":["d1"],"question_id":"q1",'
            b'"ranked_retrieved_hits":["d1"],'
            b'"scoring_family":"deterministic-retrieval",'
            b'"stored_records":["d1"]}\n',
            "question IDs",
        ),
    ],
)
def test_reproducibility_trace_population_is_well_formed(
    tmp_path: Path, traces: bytes, message: str
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / message, traces=traces)
    with pytest.raises(BundleError, match=message):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize(
    ("answer", "gold", "hits", "stored", "message"),
    [
        ("d1", ["d1"], ["d1"], ["d1", "d1"], "stored trace population"),
        ("d1", ["d2"], ["d1"], ["d1"], "outside its population"),
        ("d2", ["d1"], ["d1"], ["d1"], "answer is outside"),
    ],
)
def test_reproducibility_trace_references_its_stored_population(
    tmp_path: Path,
    answer: str,
    gold: list[str],
    hits: list[str],
    stored: list[str],
    message: str,
) -> None:
    traces = _canonical(
        {
            "answer": answer,
            "gold_references": gold,
            "question_id": "q1",
            "ranked_retrieved_hits": hits,
            "scoring_family": "deterministic-retrieval",
            "stored_records": stored,
        }
    )
    bundle = _write_reproducibility_bundle(tmp_path / message, traces=traces)
    with pytest.raises(BundleError, match=message):
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
    with pytest.raises(BundleError, match="custody|schema"):
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


def test_ledger_artifacts_without_reference_fail_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "unreferenced-ledger")
    manifest_path = bundle["root"] / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ledger_ref"] = None
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleError, match="ledger artifacts require"):
        verify_bundle(bundle["root"])


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


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    (
        ("build", "candidate_git_sha", "f" * 40),
        ("build", "system_seam", "different-seam"),
    ),
)
def test_canonical_replay_run_custody_matches_bound_artifacts(
    tmp_path: Path, section: str, field: str, replacement: str
) -> None:
    bundle = _write_reproducibility_bundle(
        tmp_path / f"replay-custody-{section}-{field}"
    )
    root = bundle["root"]
    replay_path = root / "canonical-replay.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay[section][field] = replacement
    replay_bytes = _write_json(replay_path, replay)
    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_replay"]["digest"] = canonical_replay_digest(replay)
    entry = next(
        item for item in manifest["hashes"] if item["path"] == "canonical-replay.json"
    )
    entry["size"] = len(replay_bytes)
    entry["sha256"] = _sha256_ref(replay_bytes)
    _write_json(manifest_path, manifest)
    with pytest.raises(BundleError, match="replay (?:build|config) custody mismatch"):
        verify_bundle(root)


def test_reproduce_deletes_incomplete_output_and_does_not_use_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "source")
    monkeypatch.setattr(
        "eval.public.bundle._assert_reproduction_checkout", lambda _sha, _lock: None
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


def test_final_reproduction_comparison_uses_stable_artifact_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "stable-final-source")
    destination = tmp_path / "stable-final-destination"
    original_read = public_bundle._read_inventory_file
    temp_result_reads = 0

    def read_with_final_mutation(path: Path) -> tuple[bytes, int]:
        nonlocal temp_result_reads
        payload, size = original_read(path)
        if (
            path.name == "result.json"
            and path.parent.name.startswith(f".{destination.name}-")
            and "-source-" not in path.parent.name
        ):
            temp_result_reads += 1
            if temp_result_reads == 2:
                return b"transient-mutation", len(b"transient-mutation")
        return payload, size

    monkeypatch.setattr(public_bundle, "_read_inventory_file", read_with_final_mutation)
    monkeypatch.setattr(public_bundle, "_assert_reproduction_checkout", lambda *_: None)

    with pytest.raises(BundleError, match="reproduction mismatch: result.json"):
        reproduce_bundle(bundle["root"], destination)
    assert temp_result_reads == 2
    assert not destination.exists()


def test_reproduction_rechecks_destination_ancestry_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import bundle as public_bundle

    bundle = _write_reproducibility_bundle(tmp_path / "ancestry-source")
    destination = tmp_path / "new-parent" / "ancestry-destination"
    original_reject = public_bundle._reject_reproducibility_link_path
    destination_checks = 0

    def track_destination_checks(path: Path) -> None:
        nonlocal destination_checks
        if path.absolute() == destination.absolute():
            destination_checks += 1
        original_reject(path)

    monkeypatch.setattr(
        public_bundle,
        "_reject_reproducibility_link_path",
        track_destination_checks,
    )
    monkeypatch.setattr(public_bundle, "_assert_reproduction_checkout", lambda *_: None)

    assert reproduce_bundle(bundle["root"], destination)["valid"] is True
    assert destination_checks == 3


def test_digest_consistent_malformed_lockfile_fails_closed(tmp_path: Path) -> None:
    bundle = _write_reproducibility_bundle(tmp_path / "malformed-lock")
    root = bundle["root"]
    invalid_lock = b"not = [valid toml\n"
    (root / "uv.lock").write_bytes(invalid_lock)
    manifest_path = root / REPRO_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["build"]["lockfile"] = _named_ref("uv.lock", invalid_lock)
    entry = next(item for item in manifest["hashes"] if item["path"] == "uv.lock")
    entry["size"] = len(invalid_lock)
    entry["sha256"] = _sha256_ref(invalid_lock)
    _write_json(manifest_path, manifest)
    with pytest.raises(BundleError, match="uv.lock is invalid"):
        verify_bundle(root)


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (b"version = 1", b"version = true"),
        (b"revision = 3", b"revision = true"),
        (b'requires-python = ">=3.12"', b'requires-python = ""'),
    ),
)
def test_lockfile_scalar_contract_fails_closed(
    tmp_path: Path, old: bytes, new: bytes
) -> None:
    lockfile = (REPO_ROOT / "uv.lock").read_bytes().replace(old, new, 1)
    bundle = _write_reproducibility_bundle(
        tmp_path / "invalid-lock-scalar", lockfile=lockfile
    )
    with pytest.raises(BundleError, match="lock contract"):
        verify_bundle(bundle["root"])


def test_lockfile_requires_resolved_verifier_packages(tmp_path: Path) -> None:
    lockfile = b'''version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "mnemosyne-memory"
source = { editable = "." }
dependencies = [
    { name = "cryptography" },
    { name = "jsonschema" },
]
'''
    bundle = _write_reproducibility_bundle(
        tmp_path / "unresolved-verifier-dependencies", lockfile=lockfile
    )

    with pytest.raises(BundleError, match="resolved verifier packages"):
        verify_bundle(bundle["root"])


@pytest.mark.parametrize(
    "stub",
    (
        b'name = "cryptography"\nsource = { registry = "https://pypi.org/simple" }',
        b'name = "cryptography"\nversion = "50.0.0"',
    ),
)
def test_lockfile_rejects_incomplete_resolved_package_records(
    tmp_path: Path, stub: bytes
) -> None:
    lockfile = b'''version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "mnemosyne-memory"
source = { editable = "." }
dependencies = [
    { name = "cryptography" },
    { name = "jsonschema" },
]

[[package]]
''' + stub + b'''

[[package]]
name = "jsonschema"
version = "4.26.0"
source = { registry = "https://pypi.org/simple" }
'''
    bundle = _write_reproducibility_bundle(
        tmp_path / "incomplete-verifier-package", lockfile=lockfile
    )

    with pytest.raises(BundleError, match="resolved verifier packages"):
        verify_bundle(bundle["root"])


def _clone_clean_checkout(tmp_path: Path) -> Path:
    clone = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", str(REPO_ROOT), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    leased = (
        Path("pyproject.toml"),
        Path("uv.lock"),
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
    bundle = _write_reproducibility_bundle(
        tmp_path / "clean-source",
        run_commit=sha,
        lockfile=(clone / "uv.lock").read_bytes(),
    )
    destination = tmp_path / "clean-dest"
    env = {
        "HOME": str(tmp_path / "home"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": _path_with_invoking_uv(),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "TZ": "UTC",
        "UV_OFFLINE": "1",
        "UV_PROJECT_ENVIRONMENT": str(REPO_ROOT / ".venv"),
        **({"SystemRoot": os.environ["SystemRoot"]} if "SystemRoot" in os.environ else {}),
        **({"WINDIR": os.environ["WINDIR"]} if "WINDIR" in os.environ else {}),
    }
    (tmp_path / "home").mkdir()
    command = [
        _invoking_uv_command(),
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


def test_reproduction_checkout_rejects_attached_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import _assert_reproduction_checkout

    clone = _clone_clean_checkout(tmp_path)
    subprocess.run(
        ["git", "switch", "-c", "attached-reproduction"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.chdir(clone)
    with pytest.raises(BundleError, match="detached"):
        _assert_reproduction_checkout(sha, (clone / "uv.lock").read_bytes())


def test_reproduction_checkout_accepts_clean_detached_exact_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import _assert_reproduction_checkout

    clone = _clone_clean_checkout(tmp_path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.chdir(clone)
    _assert_reproduction_checkout(sha, (clone / "uv.lock").read_bytes())


def test_reproduction_checkout_rejects_bundle_lockfile_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import _assert_reproduction_checkout

    clone = _clone_clean_checkout(tmp_path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.chdir(clone)
    with pytest.raises(BundleError, match="lockfile does not match"):
        _assert_reproduction_checkout(sha, b"different-lockfile\n")


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
            lockfile=(clone / "uv.lock").read_bytes(),
        )
    else:
        bundle = _write_reproducibility_bundle(
            tmp_path / "deny-source",
            run_commit=sha,
            lockfile=(clone / "uv.lock").read_bytes(),
        )
    destination = tmp_path / "deny-dest"
    if mutation == "dirty":
        (clone / "extra-untracked.txt").write_text("dirty\n", encoding="utf-8")
    if mutation == "output-collision":
        destination.mkdir()
        (destination / "partial.json").write_text("{}\n", encoding="utf-8")
    command = [
        _invoking_uv_command(),
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
        "PATH": _path_with_invoking_uv(),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "TZ": "UTC",
        "UV_OFFLINE": "1",
        "UV_PROJECT_ENVIRONMENT": str(REPO_ROOT / ".venv"),
        **({"SystemRoot": os.environ["SystemRoot"]} if "SystemRoot" in os.environ else {}),
        **({"WINDIR": os.environ["WINDIR"]} if "WINDIR" in os.environ else {}),
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
