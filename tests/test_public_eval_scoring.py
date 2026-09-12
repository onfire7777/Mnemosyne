from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eval.public import security_calibration as security_calibration_core
from eval.public.adapters.security_calibration_probe import SCORING_FAMILY
from eval.public.bundle import BundleError, write_bundle, verify_bundle
from eval.public.runner import load_registry
from eval.public.scoring import ScoringError, normalize_answer, score_profile


def test_longmemeval_recall_and_ndcg_are_hand_checkable() -> None:
    labels = [{"question_id": "q", "gold_references": ["a", "b"]}]
    traces = [{"question_id": "q", "ranked_retrieved_hits": ["a", "x", "b"], "scoring_family": "deterministic-retrieval"}]
    scored = score_profile("longmemeval-retrieval-v1", labels, traces)
    assert scored["metrics"]["recall_at_5"] == 1.0
    assert scored["metrics"]["ndcg_at_5"] == pytest.approx((1 + 1 / 2) / (1 + 1 / 1.584962500721156))
    assert scored["interval"]["method"] == "bootstrap"


def test_hipporag_fractional_recall_rejects_duplicate_ranked_ids() -> None:
    labels = [{"question_id": "q", "gold_references": ["a", "b", "c"]}]
    traces = [{"question_id": "q", "ranked_retrieved_hits": ["a", "a", "b", "x", "c"], "scoring_family": "deterministic-retrieval"}]
    with pytest.raises(ScoringError, match="duplicate"):
        score_profile("hipporag-retrieval-v1", labels, traces)
    traces[0]["ranked_retrieved_hits"] = ["a", "b", "x", "c"]
    scored = score_profile("hipporag-retrieval-v1", labels, traces)
    assert scored["metrics"] == {"recall_at_2": pytest.approx(2 / 3), "recall_at_5": 1.0}


def test_qa_em_f1_normalization_and_interval_families_stay_separate() -> None:
    assert normalize_answer(" The Café! ") == "café"
    labels = [{"question_id": "q", "answers": ["the red fox"]}]
    traces = [{"question_id": "q", "answer": "red fox", "scoring_family": "qa"}]
    scored = score_profile("qa-em-f1-v1", labels, traces)
    assert scored["metrics"] == {"exact_match": 1.0, "token_f1": 1.0}
    assert scored["intervals"]["exact_match"]["method"] == "wilson"
    assert scored["intervals"]["token_f1"]["method"] == "bootstrap"
    with pytest.raises(ScoringError, match="family"):
        score_profile("qa-em-f1-v1", labels, [{**traces[0], "scoring_family": "deterministic-retrieval"}])


def test_scoring_recomputes_from_labels_and_rejects_schema_ambiguity() -> None:
    labels = [{"question_id": "q", "gold_references": ["a"]}]
    traces = [{"question_id": "q", "ranked_retrieved_hits": ["a"], "claimed_score": 0.0, "scoring_family": "deterministic-retrieval"}]
    assert score_profile("hipporag-retrieval-v1", labels, traces)["metrics"]["recall_at_2"] == 1.0
    with pytest.raises(ScoringError, match="question"):
        score_profile("hipporag-retrieval-v1", labels, traces + traces)


def test_every_trace_must_declare_exact_scoring_family() -> None:
    labels = [{"question_id": "q", "gold_references": ["a"]}]
    with pytest.raises(ScoringError, match="family"):
        score_profile("hipporag-retrieval-v1", labels, [{"question_id": "q", "ranked_retrieved_hits": ["a"]}])


def test_qa_abstention_scores_only_canonical_empty_answer() -> None:
    labels = [{"answers": ["known"], "question_id": "q"}]
    traces = [{"answer": "", "question_id": "q", "scoring_family": "qa"}]
    scored = score_profile("qa-em-f1-v1", labels, traces)
    assert scored["metrics"] == {"exact_match": 0.0, "token_f1": 0.0}


def test_working_action_dispatch_preserves_categories_safety_and_metadata() -> None:
    categories = (
        "active_goal",
        "current_plan_step",
        "active_constraint",
        "unresolved_question",
        "recent_tool_result",
        "intermediate_conclusion",
    )
    labels = [
        {
            "case_id": f"case-{index}",
            "category": category,
            "expected_action_id": f"action-{index}",
            "expected_abstain": False,
            "seed": 94125,
        }
        for index, category in enumerate(categories)
    ]
    traces = [
        {
            "case_id": f"case-{index}",
            "category": category,
            "status": "action",
            "predicted_action_id": f"action-{index}",
            "scoring_family": "deterministic-action",
            "hard_gate_violations": {
                "fixture_gold_exposed_to_policy": 0,
                "foreign_scope_visible": 0,
                "payload_executed": 0,
                "automatic_durable_promotion": 0,
            },
        }
        for index, category in enumerate(categories)
    ]
    scored = score_profile("working-memory-action-v1", labels, traces)
    assert scored["family"] == "deterministic-action"
    assert scored["profile_version"] == 1
    assert scored["interval"]["method"] == "bootstrap"
    assert [row["category"] for row in scored["category_rows"]] == list(categories)
    assert not any(scored["hard_gate_violations"].values())


def _security_calibration_observations(
    fixture: dict,
    *,
    case_id: str | None = None,
    observation: dict | None = None,
) -> list[dict]:
    rows = []
    for case in fixture["cases"]:
        label = fixture["labels"][case["case_id"]]
        if label["expected_state"] == "abstained":
            row = {
                "accessed_ids": [],
                "action": "abstain",
                "case_id": case["case_id"],
                "confidence": 1.0,
                "mutation_targets": [],
                "provenance_ids": [],
                "response_text": None,
                "resurrected_ids": [],
                "scoring_family": SCORING_FAMILY,
                "state": "abstained",
                "visible_sessions": [case["session_id"]],
                "visible_tenants": [case["tenant_id"]],
            }
        else:
            row = {
                "accessed_ids": [],
                "action": label["expected_action"],
                "case_id": case["case_id"],
                "confidence": 1.0,
                "mutation_targets": [],
                "provenance_ids": [],
                "response_text": label["correct_response"],
                "resurrected_ids": [],
                "scoring_family": SCORING_FAMILY,
                "state": "answered",
                "visible_sessions": [case["session_id"]],
                "visible_tenants": [case["tenant_id"]],
            }
        if case_id is not None and case["case_id"] == case_id and observation:
            row.update(observation)
        rows.append(row)
    return rows


def test_security_calibration_profile_dispatches_without_metric_family_blending() -> None:
    fixture = security_calibration_core.generate_fixture()
    traces = _security_calibration_observations(fixture)
    expected = security_calibration_core.score(
        fixture, [{key: row[key] for key in security_calibration_core._OBSERVATION_KEYS} for row in traces]
    )
    scored = score_profile(
        "security-calibration-development-v1", [{"fixture": fixture}], traces
    )
    for key in ("security", "calibration", "abstention", "judge_diagnostics"):
        assert scored[key] == expected[key]
    assert scored["family"] == SCORING_FAMILY
    assert scored["profile"] == "security-calibration-development-v1"
    assert scored["interval"] == {"method": "descriptive"}
    assert scored["passed"] is True
    assert scored["hard_gate_failed"] is False
    assert "metrics" not in scored
    assert scored["security"]["families"]
    assert "ece" in scored["calibration"]
    assert "coverage" in scored["abstention"]
    assert "invocation_count" in scored["judge_diagnostics"]


def test_security_calibration_profile_rejects_self_scoring_and_blending() -> None:
    fixture = security_calibration_core.generate_fixture()
    traces = _security_calibration_observations(fixture)
    leaked = dict(traces[0])
    leaked["passed"] = True
    leaked["score"] = 1.0
    with pytest.raises(ScoringError, match="self-scoring"):
        score_profile(
            "security-calibration-development-v1",
            [{"fixture": fixture}],
            [leaked, *traces[1:]],
        )
    blended = dict(traces[0])
    blended["scoring_family"] = "qa"
    with pytest.raises(ScoringError, match="blended"):
        score_profile(
            "security-calibration-development-v1",
            [{"fixture": fixture}],
            [blended, *traces[1:]],
        )


def test_security_calibration_profile_rejects_claim_drift_and_official_relabeling() -> None:
    fixture = security_calibration_core.generate_fixture()
    traces = _security_calibration_observations(fixture)
    drifted = dict(fixture)
    drifted["publishable"] = True
    with pytest.raises(ScoringError, match="claim state"):
        score_profile(
            "security-calibration-development-v1", [{"fixture": drifted}], traces
        )
    relabeled = dict(fixture)
    relabeled["suite"] = "MINJA"
    with pytest.raises(ScoringError, match="official or upstream"):
        score_profile(
            "security-calibration-development-v1", [{"fixture": relabeled}], traces
        )


def test_security_calibration_hard_gate_is_not_offset_by_other_families() -> None:
    fixture = security_calibration_core.generate_fixture()
    traces = _security_calibration_observations(
        fixture,
        case_id="sc-dev-cross-tenant-isolation",
        observation={"visible_tenants": ["tenant-alpha", "tenant-beta"]},
    )
    scored = score_profile(
        "security-calibration-development-v1", [{"fixture": fixture}], traces
    )
    assert scored["hard_gate_failed"] is True
    assert scored["passed"] is False
    assert scored["hard_failures"]
    assert scored["calibration"]["ece"] == 0.0
    assert scored["security"]["families"]["cross_tenant_isolation"]["successful_attacks"] == 1


def test_security_calibration_bundle_registers_profile_and_fixture_labels() -> None:
    from eval.public import bundle as public_bundle

    fixture = security_calibration_core.generate_fixture()
    assert public_bundle._REGISTERED_SCORING_PROFILES[
        "security-calibration-development-v1"
    ] == ("security-calibration-development", "descriptive")
    assert public_bundle._scoring_labels(fixture) == [{"fixture": fixture}]


def test_security_calibration_bundle_verify_recomputes_and_rejects_blending(
    tmp_path: Path,
) -> None:
    fixture = security_calibration_core.generate_fixture()
    traces = _security_calibration_observations(fixture)
    suite = load_registry()["security-calibration-style-development-v1"]
    measured = score_profile(
        "security-calibration-development-v1", [{"fixture": fixture}], traces
    )
    source = tmp_path / "source"
    write_bundle(
        source,
        benchmark=fixture,
        metadata={**suite, "suite": "security-calibration-style-development-v1"},
        metrics=measured,
        traces=traces,
    )
    assert verify_bundle(source) == {
        "family": "security-calibration-development",
        "suite": "security-calibration-style-development-v1",
        "valid": True,
    }
    tampered = [dict(row) for row in traces]
    tampered[0]["scoring_family"] = "qa"
    (source / "traces.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in tampered
        )
    )
    manifest = json.loads((source / "bundle-manifest.json").read_text())
    manifest["files"]["traces.jsonl"] = hashlib.sha256(
        (source / "traces.jsonl").read_bytes()
    ).hexdigest()
    (source / "bundle-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(BundleError, match="blended"):
        verify_bundle(source)

