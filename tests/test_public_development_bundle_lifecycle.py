"""Registered development cells retain verifiable and reproducible custody."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from eval.public.bundle import BundleError, verify_bundle, reproduce_bundle
from eval.public.runner import run_public_suite


@pytest.mark.parametrize(
    "suite",
    [
        "wmbs-m02-retrieval-development",
        "wmbs-m04-development",
        "wmbs-m06-development",
    ],
)
def test_registered_development_bundle_round_trip(
    tmp_path: Path, suite: str, monkeypatch
) -> None:
    # M02/M04 need a configured reader; this tests bundle plumbing with an
    # explicitly synthetic CLI, never product answering or benchmark quality.
    if suite != "wmbs-m06-development":
        monkeypatch.setattr("eval.public.runner.MnemoCLI", SyntheticCLI)
    source, destination = tmp_path / "source", tmp_path / "reproduced"
    result = run_public_suite(suite, source)
    for flag in (
        "publishable",
        "pbpp_headline_eligible",
        "independent_external_reproduction",
    ):
        assert result[flag] is False
    metadata = json.loads((source / "benchmark.json").read_text())["metadata"]
    assert metadata["admission_state"] == "PROPOSED"
    assert metadata["headline_eligible"] is False
    assert metadata["upstream_comparable"] is False
    assert verify_bundle(source)["valid"] is True
    reproduce_bundle(source, destination)
    assert verify_bundle(destination) == verify_bundle(source)
    for path in source.iterdir():
        assert path.read_bytes() == (destination / path.name).read_bytes()
    # Re-signing file hashes cannot hide altered metrics or missing observations.
    for tamper in ("metric", "missing", "duplicate", "family"):
        damaged = tmp_path / tamper
        shutil.copytree(source, damaged)
        if tamper == "metric":
            name = "metrics.json"
            payload = json.loads((damaged / name).read_text())
            payload["passed"] = not payload.get("passed", False)
            raw = json.dumps(payload).encode()
        else:
            name = "traces.jsonl"
            rows = (damaged / name).read_text().splitlines()
            if tamper == "missing":
                rows.pop()
            elif tamper == "duplicate":
                rows.append(rows[0])
            else:
                row = json.loads(rows[0])
                row["scoring_family"] = "qa"
                rows[0] = json.dumps(row)
            raw = ("\n".join(rows) + "\n").encode()
        (damaged / name).write_bytes(raw)
        manifest = json.loads((damaged / "bundle-manifest.json").read_text())
        manifest["files"][name] = hashlib.sha256(raw).hexdigest()
        (damaged / "bundle-manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(BundleError):
            verify_bundle(damaged)


@pytest.mark.parametrize(
    ("suite", "seeds"),
    [
        ("wmbs-m02-retrieval-development", [20260801]),
        ("wmbs-m04-development", [11, 23, 37, 53, 71]),
        ("wmbs-m06-development", [17, 31, 43, 61, 79]),
    ],
)
def test_development_replay_binds_complete_seed_set(suite, seeds) -> None:
    from eval.public.bundle import BundleError, canonical_replay_digest

    payload = {
        "abi_schema": "wmbs/0.1-draft",
        "build": {},
        "config": {"locale": "C", "timezone": "UTC"},
        "fixture": suite + "@sha256:" + "a" * 64,
        "judge": {"reader": None, "judge": None},
        "manifests": {
            "bundle_manifest_sha256": "b" * 64,
            "fixture_manifest_sha256": "a" * 64,
            "generator_manifest_sha256": "c" * 64,
        },
        "metrics": {},
        "seed_records": seeds,
        "suite": suite,
        "sut_outputs": [],
        "traces": [],
        "volatile": {},
    }
    original = canonical_replay_digest(payload)
    payload["seed_records"] = seeds[:-1]
    with pytest.raises(BundleError, match="seed records"):
        canonical_replay_digest(payload)
    payload["seed_records"] = seeds
    payload["sut_outputs"] = [{"answer": "changed"}]
    assert canonical_replay_digest(payload) != original


class SyntheticCLI:
    """Synthetic transport returns no answers and ignores benchmark gold."""

    backend = "local"
    global_flags = []

    def __init__(self, store, env):
        self.ids = []

    def capture(self, tenant, user, content, *, source_identity):
        self.ids.append(source_identity)
        return {"cid": source_identity}

    def assert_fact(self, *args, **kwargs):
        return {"ok": True}

    def search(self, *args, **kwargs):
        return {"hits": self.ids[:10]}

    def graph_as_of(self, *args, **kwargs):
        return {"assertions": []}

    def answer(self, *args, **kwargs):
        return {"answer": None, "abstained": True}


def test_m02_reaches_provider_gate_through_read_only_cli(tmp_path, monkeypatch):
    from eval.harness.cli_driver import CLIError, MnemoCLI
    from eval.public import wmbs_m02
    from eval.public.adapters.whole_memory_reference import (
        run_m02_retrieval_development,
    )

    monkeypatch.delenv("MNEMOSYNE_GROUNDED_READER_COMMAND", raising=False)
    monkeypatch.delenv("MNEMOSYNE_QUERY_DECOMPOSER_COMMAND", raising=False)
    fixture = wmbs_m02.load_fixture()
    fixture["corpus"] = fixture["corpus"][:1]
    fixture["questions"] = [fixture["questions"][-1]]
    fixture.pop("fixture_sha256")
    with pytest.raises(
        CLIError, match="grounded answer role commands are not configured"
    ):
        run_m02_retrieval_development(
            fixture, MnemoCLI(store=str(tmp_path / "store.json"))
        )
