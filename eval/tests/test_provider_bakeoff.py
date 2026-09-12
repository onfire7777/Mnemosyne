from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from eval.provider_bakeoff.run import (  # noqa: E402
    CAP006_PROVIDER_SCHEMA,
    PHASE15_S4_PROVIDER_REPORT,
    build_report,
    decide_provider_default,
    pinned_identical_workload,
    run_provider_bakeoff,
    verify_candidate_license,
)


def _write_slo_report(path: Path, *, recall: float, passed: bool = True) -> None:
    payload = {
        "meta": {"backend": "local", "quick": True},
        "ignition": {"mode": "SHADOW", "suite_size": 25, "ignition_n": 40},
        "overall": {"passed": 2 if passed else 1, "total": 2, "all_pass": passed},
        "slo_suites": [
            {
                "suite": "retrieval",
                "verdicts": [
                    {
                        "name": "recall@k",
                        "value": recall,
                        "target": 0.8,
                        "op": ">=",
                        "pass": passed,
                        "ci": {
                            "point": recall,
                            "ci_low": max(0.0, recall - 0.1),
                            "ci_high": min(1.0, recall + 0.1),
                            "ci_method": "bootstrap",
                        },
                    }
                ],
            }
        ],
        "mandatory_classes": [{"name": "no_degradation_vs_no_memory", "passed": True}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_suffix(".md").write_text("# SLO report\n", encoding="utf-8")


def _write_fixture(tmp_path: Path, *, baseline: Path, candidate: Path, promotion_allowed: bool = False) -> Path:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "protocol": "mnemosyne-provider-bakeoff-v1",
                "purpose": "test fixture",
                "promotion_allowed_from_smoke": promotion_allowed,
                "acceptance": {
                    "non_inferior_required": True,
                    "protected_case_regression_allowed": False,
                    "margin_must_exceed_run_to_run_noise": True,
                    "confidence_intervals_required": True,
                    "public_benchmarks_are_claims": False,
                },
                "arms": [
                    {
                        "name": "baseline",
                        "kind": "baseline",
                        "command": ["python", "eval/run_eval.py"],
                        "report": str(baseline),
                    },
                    {
                        "name": "candidate",
                        "kind": "candidate-smoke",
                        "command": ["python", "eval/run_eval.py"],
                        "report": str(candidate),
                    },
                ],
                "required_evidence": [
                    "baseline_report_json",
                    "candidate_report_json",
                    "baseline_report_markdown",
                    "candidate_report_markdown",
                    "provider_check_report",
                    "noise_or_rerun_notes",
                ],
            }
        ),
        encoding="utf-8",
    )
    return fixture


def test_provider_bakeoff_blocks_smoke_promotion_with_complete_evidence(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_slo_report(baseline, recall=0.82)
    _write_slo_report(candidate, recall=0.83)
    provider_check = tmp_path / "provider-check.json"
    provider_check.write_text(json.dumps({"ok": True, "checks": {"embedding": {"ok": True}}}), encoding="utf-8")
    noise_notes = tmp_path / "noise.md"
    noise_notes.write_text("rerun noise envelope recorded\n", encoding="utf-8")

    report = build_report(
        _write_fixture(tmp_path, baseline=baseline, candidate=candidate),
        provider_check_report=provider_check,
        noise_notes=noise_notes,
        cwd=_REPO,
    )

    assert report["ok"] is True
    assert report["missing_evidence"] == []
    assert report["evidence"]["provider_check_report"] is True
    retrieval_metric = next(
        item for item in report["comparisons"][0]["metrics"] if item["metric"] == "retrieval.curated:recall@k"
    )
    assert retrieval_metric["delta"] > 0
    assert report["promotion"]["allowed"] is False
    assert report["promotion"]["reasons"] == ["fixture_does_not_allow_promotion"]


def test_provider_bakeoff_flags_candidate_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_slo_report(baseline, recall=0.82, passed=True)
    _write_slo_report(candidate, recall=0.72, passed=False)
    provider_check = tmp_path / "provider-check.json"
    provider_check.write_text(json.dumps({"ok": True}), encoding="utf-8")
    noise_notes = tmp_path / "noise.md"
    noise_notes.write_text("rerun noise envelope recorded\n", encoding="utf-8")

    report = build_report(
        _write_fixture(tmp_path, baseline=baseline, candidate=candidate, promotion_allowed=True),
        provider_check_report=provider_check,
        noise_notes=noise_notes,
        cwd=_REPO,
    )

    assert report["ok"] is False
    assert report["comparisons"][0]["regressions"]
    assert "candidate_regression" in report["promotion"]["reasons"]
    assert any(item["code"] == "candidate_regression" for item in report["findings"])


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_canonical(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _digest_for(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest()


def _license(
    *,
    source: str = "spdx",
    identifier: str = "Apache-2.0",
    status: str | None = None,
    evidence: str | None = None,
    evidence_digest: str | None = None,
) -> dict[str, object]:
    text = evidence if evidence is not None else f"{source}:{identifier}"
    digest = (
        evidence_digest
        if evidence_digest is not None
        else "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    )
    record: dict[str, object] = {
        "source": source,
        "identifier": identifier,
        "evidence": text,
        "evidence_digest": digest,
    }
    if status is not None:
        record["verification_status"] = status
    return record


def _candidate(
    name: str,
    *,
    kind: str = "measured",
    installed: bool = True,
    available: bool = True,
    supported: bool = True,
    digest: str | None = None,
    license_record: dict[str, object] | None = None,
    embed=None,
) -> dict[str, object]:
    candidate: dict[str, object] = {
        "name": name,
        "kind": kind,
        "installed": installed,
        "available": available,
        "supported": supported,
        "digest": digest if digest is not None else _digest_for(name),
        "license": license_record if license_record is not None else _license(),
    }
    if embed is not None:
        candidate["embed"] = embed
    return candidate


def test_candidate_identity_is_digest_pinned_and_license_bound() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    assert receipt["schema"] == CAP006_PROVIDER_SCHEMA
    names = []
    for candidate in receipt["candidates"]:
        names.append(candidate["name"])
        assert candidate["digest"].startswith("sha256:")
        assert len(candidate["digest"].removeprefix("sha256:")) == 64
        license_record = candidate["license"]
        assert license_record["source"]
        assert license_record["identifier"]
        assert license_record["evidence_digest"].startswith("sha256:")
        assert license_record["verification_status"] == "verified"
        assert candidate["identity"]["name"] == candidate["name"]
        assert candidate["identity"]["digest"] == candidate["digest"]
    assert names == ["synthetic-a", "synthetic-b"]


def test_identical_corpus_queries_batching_and_dimensions() -> None:
    first = pinned_identical_workload()
    second = pinned_identical_workload()
    assert first == second
    for field in ("corpus", "queries", "batching", "dimensions"):
        assert field in first
        assert first[field]
    assert first["batching"]["size"] >= 1
    assert isinstance(first["dimensions"], int) and first["dimensions"] > 0
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    comparison = receipt["comparison"]
    assert comparison["identical_corpus"] is True
    assert comparison["identical_queries"] is True
    assert comparison["identical_batching"] is True
    assert comparison["identical_dimensions"] is True
    assert comparison["workload_digest"] == first["workload_digest"]
    seen_workloads = []
    for candidate in receipt["candidates"]:
        if candidate.get("status") == "compared":
            seen_workloads.append(candidate["workload_digest"])
            assert candidate["corpus_digest"] == first["corpus_digest"]
            assert candidate["queries_digest"] == first["queries_digest"]
            assert candidate["batching"] == first["batching"]
            assert candidate["dimensions"] == first["dimensions"]
    assert seen_workloads
    assert len(set(seen_workloads)) == 1


def test_cold_and_warm_are_separated() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    for candidate in receipt["candidates"]:
        if candidate.get("status") != "compared":
            continue
        assert candidate["cold"]["separated_from_warm"] is True
        assert candidate["warm"]["separated_from_cold"] is True
        assert candidate["cold"]["sample_count"] >= 1
        assert candidate["warm"]["sample_count"] >= 1
        assert candidate["cold"]["observations"]
        assert candidate["warm"]["observations"]
        cold_ids = [item["op_id"] for item in candidate["cold"]["observations"]]
        warm_ids = [item["op_id"] for item in candidate["warm"]["observations"]]
        assert cold_ids
        assert warm_ids
        assert set(cold_ids).isdisjoint(set(warm_ids)) or all(
            item.get("phase") == "cold" for item in candidate["cold"]["observations"]
        )
        assert all(item["phase"] == "cold" for item in candidate["cold"]["observations"])
        assert all(item["phase"] == "warm" for item in candidate["warm"]["observations"])
        assert receipt["workload"]["cold_warm_state"] == "separated"


def test_correctness_and_embedding_shape_parity() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    compared = [item for item in receipt["candidates"] if item["status"] == "compared"]
    assert len(compared) >= 2
    dims = pinned_identical_workload()["dimensions"]
    shapes = []
    correctness = []
    for candidate in compared:
        shape = candidate["embedding_shape"]
        assert shape["dims"] == dims
        assert shape["parity"] is True
        assert shape["vector_count"] >= 1
        assert all(length == dims for length in shape["observed_lengths"])
        assert candidate["correctness"]["pass"] is True
        assert candidate["correctness"]["parity"] is True
        shapes.append(shape["dims"])
        correctness.append(candidate["correctness"]["hits"])
    assert len(set(shapes)) == 1
    assert len({_canonical_json(hits) for hits in correctness}) == 1


def test_errors_remain_in_denominators() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
        inject_outcomes={"synthetic-a": {"q_capital_france": "error", "q_capital_germany": "timeout"}},
    )
    failing = next(item for item in receipt["candidates"] if item["name"] == "synthetic-a")
    denominators = failing["denominators"]
    assert denominators["issued"] == (
        denominators["successes"] + denominators["timeouts"] + denominators["errors"]
    )
    assert denominators["errors"] >= 1
    assert denominators["timeouts"] >= 1
    assert denominators["failed_remain_in_denominator"] is True
    outcomes = {item["outcome"] for item in failing["observations"]}
    assert "error" in outcomes
    assert "timeout" in outcomes


def test_noise_and_load_reject_decision() -> None:
    noisy = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
        host_noise=True,
    )
    loaded = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
        extra_load=True,
    )
    assert noisy["noise_load"]["noise_detected"] is True
    assert noisy["noise_load"]["rejected"] is True
    assert loaded["noise_load"]["load_detected"] is True
    assert loaded["noise_load"]["rejected"] is True
    assert noisy["decision"]["decision"] == "no-decision"
    assert loaded["decision"]["decision"] == "no-decision"
    assert "noise_rejected" in noisy["decision"]["blockers"]
    assert "load_rejected" in loaded["decision"]["blockers"]


def test_cost_and_resource_fields_are_present() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    for sample_name in ("before", "after"):
        sample = receipt["resources"][sample_name]
        for field in (
            "total_memory_bytes",
            "free_memory_bytes",
            "available_memory_bytes",
            "swap_bytes",
            "process_rss_bytes",
            "process_pss_or_working_set_bytes",
            "vram_bytes",
            "disk_bytes",
            "network_bytes",
            "load_averages",
            "cpu_seconds",
        ):
            assert field in sample, f"resource sample missing {field}"
    assert receipt["resources"]["during"]
    for candidate in receipt["candidates"]:
        if candidate.get("status") != "compared":
            continue
        cost = candidate["cost"]
        assert cost["embed_calls"] >= 1
        assert cost["batch_count"] >= 1
        assert "estimated_units" in cost
        assert candidate["resources"]["before"]
        assert candidate["resources"]["after"]


def test_decision_output_is_deterministic() -> None:
    candidates = [_candidate("synthetic-a"), _candidate("synthetic-b")]
    first = run_provider_bakeoff(candidates, current_default="local")
    second = run_provider_bakeoff(candidates, current_default="local")
    assert first["decision"] == second["decision"]
    assert first["decision"]["decision"] in {"select", "no-decision"}
    assert first["decision"]["blockers"] == sorted(first["decision"]["blockers"])
    replay = decide_provider_default(first)
    assert replay == first["decision"]
    assert replay == decide_provider_default(second)


def test_missing_rejected_or_unverifiable_license_forces_no_decision() -> None:
    missing = run_provider_bakeoff(
        [
            _candidate("licensed", license_record=_license()),
            _candidate(
                "unlicensed",
                license_record={"source": "", "identifier": "", "evidence_digest": ""},
            ),
        ],
        current_default="local",
    )
    rejected = run_provider_bakeoff(
        [
            _candidate("licensed", license_record=_license()),
            _candidate("rejected", license_record=_license(status="rejected")),
        ],
        current_default="local",
    )
    unverifiable = run_provider_bakeoff(
        [
            _candidate("licensed", license_record=_license()),
            _candidate(
                "opaque",
                license_record=_license(evidence_digest="not-a-digest"),
            ),
        ],
        current_default="local",
    )
    for receipt, status, name in (
        (missing, "missing", "unlicensed"),
        (rejected, "rejected", "rejected"),
        (unverifiable, "unverifiable", "opaque"),
    ):
        candidate = next(item for item in receipt["candidates"] if item["name"] == name)
        assert candidate["license"]["verification_status"] == status
        assert receipt["decision"]["decision"] == "no-decision"
        assert any(status in blocker for blocker in receipt["decision"]["blockers"])
        computed = verify_candidate_license(candidate["license"])
        assert computed["verification_status"] == status


def test_unsupported_and_unavailable_are_recorded_not_simulated() -> None:
    receipt = run_provider_bakeoff(
        [
            _candidate("synthetic-a"),
            _candidate("tei", kind="unsupported", supported=False, available=False),
            _candidate("onnx-missing", kind="unavailable", installed=False, available=False),
        ],
        current_default="local",
    )
    recorded = {item["name"]: item for item in receipt["candidates"]}
    assert recorded["tei"]["status"] == "recorded-unsupported"
    assert recorded["onnx-missing"]["status"] == "recorded-unavailable"
    assert recorded["tei"]["simulated"] is False
    assert recorded["onnx-missing"]["simulated"] is False
    assert "observations" not in recorded["tei"] or recorded["tei"].get("observations") == []
    assert recorded["tei"].get("correctness") is None or recorded["tei"]["correctness"].get("simulated") is False
    assert "unsupported_or_unavailable_recorded" in receipt["decision"]["blockers"] or receipt["decision"]["decision"] in {
        "select",
        "no-decision",
    }


def test_smoke_success_never_selects_a_default() -> None:
    receipt = run_provider_bakeoff(
        [
            _candidate("smoke-a", kind="smoke"),
            _candidate("smoke-b", kind="smoke"),
        ],
        current_default="local",
    )
    assert receipt["ok"] is True or receipt["candidates"]
    assert all(item["kind"] == "smoke" for item in receipt["candidates"])
    assert receipt["decision"]["decision"] == "no-decision"
    assert "smoke_success_does_not_select_default" in receipt["decision"]["blockers"]
    assert receipt["decision"]["selected"] is None
    assert receipt["decision"]["config_promotion"] is False


def test_default_decision_requires_measured_evidence_and_names_rollback() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    decision = receipt["decision"]
    assert decision["decision"] == "select"
    assert decision["selected"] in {"synthetic-a", "synthetic-b"}
    assert decision["rollback_value"] == "local"
    assert decision["requires_retained_measured_evidence"] is True
    assert decision["config_promotion"] is False
    assert decision["blockers"] == []
    selected = next(item for item in receipt["candidates"] if item["name"] == decision["selected"])
    assert selected["kind"] == "measured"
    assert selected["license"]["verification_status"] == "verified"
    assert selected["installed"] is True
    assert selected["digest"].startswith("sha256:")


def test_cap006_provider_receipt_makes_no_official_p95_claim() -> None:
    receipt = run_provider_bakeoff(
        [_candidate("synthetic-a"), _candidate("synthetic-b")],
        current_default="local",
    )
    assert receipt["official_claim"] is False
    assert receipt["admitted_measurement"] is False
    assert receipt["claim_status"] == "synthetic-development-receipt-only"
    assert receipt["official_p95_claim"] is False
    assert receipt["performance_claim"] is None
    identity = receipt["identity"]
    assert len(identity["repository_sha"]) == 40
    assert isinstance(identity["clean_tree"], bool)
    assert identity["command"]
    assert Path(str(identity["command"][-1])).name == "run.py"
    for field in (
        "dataset",
        "fixture",
        "config",
        "model",
        "tokenizer",
        "provider",
        "container_image",
        "schema",
        "result_contract",
    ):
        assert identity["digests"][field].startswith("sha256:")
    assert receipt["sut_boundary"]["benchmark_process_count"] == 1
    assert receipt["sut_boundary"]["host_workload_count"] == 1
    raw = receipt["raw_artifacts"]
    for field in ("observations_sha256", "workload_sha256", "result_digest"):
        assert raw[field].startswith("sha256:")
    complete = json.loads(_canonical_json(receipt))
    complete["raw_artifacts"].pop("result_digest", None)
    assert raw["result_digest"] == "sha256:" + _sha256_canonical(complete)


def test_phase15_s4_provider_receipt_is_synthetic_development_evidence() -> None:
    assert PHASE15_S4_PROVIDER_REPORT.is_file()
    receipt = json.loads(PHASE15_S4_PROVIDER_REPORT.read_text(encoding="utf-8"))
    assert receipt["schema"] == CAP006_PROVIDER_SCHEMA
    assert receipt["receipt_class"] == "synthetic-development"
    assert receipt["official_claim"] is False
    assert receipt["official_p95_claim"] is False
    assert receipt["admitted_measurement"] is False
    assert receipt["decision"]["config_promotion"] is False
    assert receipt["decision"]["decision"] in {"select", "no-decision"}
    if receipt["decision"]["decision"] == "select":
        assert receipt["decision"]["selected"]
        assert receipt["decision"]["rollback_value"]
        assert receipt["decision"]["blockers"] == []
    else:
        assert receipt["decision"]["selected"] is None
        assert receipt["decision"]["blockers"]
        assert receipt["decision"]["blockers"] == sorted(receipt["decision"]["blockers"])
    for candidate in receipt["candidates"]:
        assert "source" in candidate["license"]
        assert "identifier" in candidate["license"]
        assert "evidence_digest" in candidate["license"]
        assert "verification_status" in candidate["license"]
    assert Path(str(receipt["identity"]["command"][-1])).name == "run.py"
