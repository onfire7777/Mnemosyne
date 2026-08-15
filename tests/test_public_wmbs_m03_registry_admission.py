"""Pin the M03 valid-time development suite's public-registry admission.

Node `T9` of `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
admits the already-built M03 valid-time cell to `eval/public/registry.json` so it
is reachable from `run_public_suite`. This is a reachability fix only: M03 stays
`PROPOSED`, non-publishable, and non-comparable, and full bitemporal
transaction-time query semantics stay deferred.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from eval.public import bundle as public_bundle
from eval.public.adapters import whole_memory_reference
from eval.public.runner import _ADAPTERS, _PROFILE_CONTRACTS, load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE = "wmbs-m03-valid-time-development"
FIXTURE = REPO_ROOT / "eval/public/fixtures/wmbs-m03-valid-time-development.json"


@pytest.fixture(scope="module")
def suite() -> dict[str, object]:
    registry = load_registry()
    assert SUITE in registry, "M03 valid-time suite is unreachable from the registry"
    return registry[SUITE]


def test_registry_entry_declares_the_committed_fixture(
    suite: dict[str, object],
) -> None:
    assert suite["fixture"] == "fixtures/wmbs-m03-valid-time-development.json"
    assert (REPO_ROOT / "eval/public" / str(suite["fixture"])) == FIXTURE
    assert FIXTURE.is_file()


def test_registry_digest_recomputes_from_the_committed_fixture(
    suite: dict[str, object],
) -> None:
    benchmark = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # The runner applies no normalizer to fixture-based whole-memory suites, so
    # the registry digest is the canonicalization of the fixture as loaded.
    digest = hashlib.sha256(public_bundle._canonical(benchmark)).hexdigest()

    assert suite["dataset_sha256"] == digest


def test_registry_revision_pins_the_fixture_s_last_commit(
    suite: dict[str, object],
) -> None:
    revision = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(FIXTURE.relative_to(REPO_ROOT))],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
        text=True,
    ).stdout.strip()

    assert suite["revision"] == revision


def test_adapter_key_resolves_to_the_m03_valid_time_adapter(
    suite: dict[str, object],
) -> None:
    assert suite["adapter"] == "wmbs-m03-valid-time-reference"
    assert (
        _ADAPTERS[str(suite["adapter"])]
        is whole_memory_reference.run_m03_valid_time_development
    )


def test_profile_contract_matches_the_declared_family_and_interval(
    suite: dict[str, object],
) -> None:
    assert suite["scoring_profile"] == "wmbs-m03-valid-time-v1"
    assert _PROFILE_CONTRACTS[str(suite["scoring_profile"])] == (
        suite["family"],
        suite["interval_method"],
    )
    assert suite["family"] == "whole-memory-development"
    assert suite["interval_method"] == "descriptive"


def test_suite_runs_through_the_public_cli_subprocess_seam(
    suite: dict[str, object],
) -> None:
    # Unlike M01/M10, this cell drives a real CLI, so it must not claim the
    # harness-owned reference core seam.
    assert "system_seam" not in suite


def test_registry_labels_stay_honest(suite: dict[str, object]) -> None:
    assert suite["admission_state"] == "PROPOSED"
    assert suite["publishable"] is False
    assert suite["pbpp_headline_eligible"] is False
    assert suite["headline_eligible"] is False
    assert suite["upstream_comparable"] is False
    assert suite["independent_external_reproduction"] is False
    assert suite["split_role"] == "development"


def test_fixture_retains_the_transaction_time_deferral() -> None:
    benchmark = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert benchmark["transaction_time"]["supported"] is False


@pytest.fixture(scope="module")
def m03_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    from eval.public.runner import run_public_suite

    out_dir = tmp_path_factory.mktemp("m03-bundle") / "bundle"
    return run_public_suite(SUITE, out_dir=str(out_dir))


def test_suite_is_reachable_end_to_end_from_run_public_suite(
    m03_run: dict[str, object],
) -> None:
    assert m03_run["suite"] == SUITE
    assert m03_run["publishable"] is False
    assert m03_run["pbpp_headline_eligible"] is False
    assert m03_run["independent_external_reproduction"] is False
    assert m03_run["system_seam"] == "public-cli-subprocess"

    verdict = public_bundle.verify_bundle(Path(str(m03_run["bundle"])))

    assert verdict["valid"] is True
    assert verdict["family"] == "whole-memory-development"
    assert verdict["suite"] == SUITE


def _retamper(bundle: Path, name: str, payload: object) -> None:
    """Rewrite one bundle file and re-seal the manifest around it."""
    (bundle / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = json.loads((bundle / "bundle-manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    (bundle / "bundle-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_bundle_pins_the_scored_denominator_to_the_fixture(
    m03_run: dict[str, object],
) -> None:
    # `total` is exempt from the trace-count equality for this profile, so it is
    # pinned instead to the count the registry-anchored fixture implies: one
    # as-of history query per (timeline history entry, seed).
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = len(fixture["seeds"]) * sum(
        len(timeline["history"]) for timeline in fixture["timelines"]
    )
    metrics = json.loads(
        (Path(str(m03_run["bundle"])) / "metrics.json").read_text(encoding="utf-8")
    )

    assert expected != len(fixture["timelines"]) * len(fixture["seeds"])
    assert metrics["total"] == expected


@pytest.mark.parametrize("total", [0, -1, "60", True, None, 59, 61, 25])
def test_bundle_rejects_a_drifted_scored_denominator(
    m03_run: dict[str, object], tmp_path: Path, total: object
) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(str(m03_run["bundle"]), bundle)
    metrics = json.loads((bundle / "metrics.json").read_text(encoding="utf-8"))
    metrics["total"] = total
    _retamper(bundle, "metrics.json", metrics)

    with pytest.raises(public_bundle.BundleError, match="trace/metric count drift"):
        public_bundle.verify_bundle(bundle)


def test_bundle_still_rejects_trace_count_drift(
    m03_run: dict[str, object], tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(str(m03_run["bundle"]), bundle)
    metrics = json.loads((bundle / "metrics.json").read_text(encoding="utf-8"))
    metrics["trace_count"] = int(metrics["trace_count"]) + 1
    _retamper(bundle, "metrics.json", metrics)

    with pytest.raises(public_bundle.BundleError, match="trace/metric count drift"):
        public_bundle.verify_bundle(bundle)


def test_bundle_profile_contract_admits_the_suite(
    m03_run: dict[str, object], tmp_path: Path
) -> None:
    # `eval/public/bundle.py` carries a second, independent profile-contract
    # table keyed on the scoring profile; the entry admitted for this suite must
    # be the same (family, interval_method) pair the bundle declares, or
    # verification fails closed with "wrong interval-family metadata".
    bundle = tmp_path / "bundle"
    shutil.copytree(str(m03_run["bundle"]), bundle)
    config = json.loads((bundle / "config.json").read_text(encoding="utf-8"))
    assert config["scoring_profile"] == "wmbs-m03-valid-time-v1"
    config["interval_method"] = "wilson"
    _retamper(bundle, "config.json", config)

    with pytest.raises(public_bundle.BundleError, match="wrong interval-family"):
        public_bundle.verify_bundle(bundle)


def test_total_exemption_is_scoped_to_the_m03_profile(tmp_path: Path) -> None:
    # The exemption must not leak to any other suite: M01 shares this family and
    # interval method, and its `total` stays pinned to the trace count.
    from eval.public.runner import run_public_suite

    run = run_public_suite("wmbs-m01-development", out_dir=str(tmp_path / "m01"))
    bundle = Path(str(run["bundle"]))
    metrics = json.loads((bundle / "metrics.json").read_text(encoding="utf-8"))
    assert public_bundle.verify_bundle(bundle)["valid"] is True
    metrics["total"] = int(metrics["total"]) + 1
    _retamper(bundle, "metrics.json", metrics)

    with pytest.raises(public_bundle.BundleError, match="trace/metric count drift"):
        public_bundle.verify_bundle(bundle)


def test_readme_documents_the_suite_with_its_deferral() -> None:
    readme = (REPO_ROOT / "eval/public/README.md").read_text(encoding="utf-8")

    assert SUITE in readme
    assert "transaction-time" in readme
