from __future__ import annotations

import pytest

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
