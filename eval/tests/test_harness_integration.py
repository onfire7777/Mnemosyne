"""Integration tests: drive the real harness against the local CLI end-to-end.

These are the proof that the harness runs NOW against the deterministic engine.
They are slower (each spawns CLI subprocesses) but exercise the actual contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from eval.harness import ignition, suites  # noqa: E402
from eval.harness.synthetic import DEFAULT_EPISODES, generate_retrieval_cases  # noqa: E402
from eval.harness.test_classes import run_all_mandatory_classes  # noqa: E402

DATASETS = _REPO / "eval" / "datasets"


def _load(name: str) -> dict:
    return json.loads((DATASETS / name).read_text())


def test_all_mandatory_classes_pass():
    """The five §33 mandatory test classes must all pass on the local engine."""
    curated = _load("retrieval_curated.json")
    results = run_all_mandatory_classes(str(DATASETS / "belief_cases.json"), curated)
    names = {r.name for r in results}
    assert names == {
        "rollback_crossing_supersession",
        "erasure_with_without_corroboration",
        "contested_belief_multi_hypothesis",
        "untrusted_instruction_never_executed",
        "no_degradation_vs_no_memory",
    }
    failed = [r.name for r in results if not r.passed]
    assert not failed, f"mandatory classes failed: {failed}: " + "; ".join(
        f"{r.name}={r.detail}" for r in results if not r.passed
    )


def test_poison_block_rate_meets_g7():
    """G7: poison block rate must be >= 0.95 even on the deterministic engine."""
    poison = _load("poison_suite.json")
    res = suites.poison_suite_eval(poison)
    assert res["block_rate"] >= 0.95
    assert res["verdicts"][0]["pass"] is True


def test_retrieval_suite_returns_real_numbers():
    curated = _load("retrieval_curated.json")
    res = suites.retrieval_suite(curated)
    # Deterministic engine still surfaces exact-match capitals -> recall is real & > 0.
    assert res["n_queries"] > 0
    assert 0.0 <= res["recall_at_k"]["mean"] <= 1.0
    assert res["recall_at_k"]["mean"] > 0.0
    # CI must bracket the point estimate.
    assert res["recall_at_k"]["ci_low"] <= res["recall_at_k"]["point"] <= res["recall_at_k"]["ci_high"]


def test_calibration_suite_emits_ece():
    curated = _load("retrieval_curated.json")
    res = suites.calibration_suite(curated)
    assert res["n"] > 0
    assert 0.0 <= res["ece"] <= 1.0
    assert res["verdicts"][0]["name"] == "ece"


def test_synthetic_generation_is_deterministic():
    a = generate_retrieval_cases(DEFAULT_EPISODES, seed=7)
    b = generate_retrieval_cases(DEFAULT_EPISODES, seed=7)
    assert a == b
    assert len(a["queries"]) == len(DEFAULT_EPISODES) * 2
    # Every synthetic query points at exactly one relevant doc that exists in corpus.
    corpus_ids = {d["doc_id"] for d in a["corpus"]}
    for q in a["queries"]:
        assert len(q["relevant_doc_ids"]) == 1
        assert q["relevant_doc_ids"][0] in corpus_ids


def test_ignition_gate_shadow_then_active(tmp_path):
    state_path = tmp_path / "suite_state.json"
    shadow = ignition.evaluate_ignition(10, 40, state_path=state_path)
    assert shadow.mode == "SHADOW"
    active = ignition.evaluate_ignition(50, 40, state_path=state_path)
    assert active.mode == "ACTIVE"
    # History accumulates across calls.
    assert len(active.history) == 2


def test_belief_revision_contested_surfaces_two_hypotheses():
    from eval.harness.test_classes import test_contested_belief_multi_hypothesis

    res = test_contested_belief_multi_hypothesis(str(DATASETS / "belief_cases.json"))
    assert res.passed
    assert res.evidence["objects"] == ["April", "March"]
    assert abs(res.evidence["probability_sum"] - 1.0) < 1e-6


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
