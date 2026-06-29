"""Tests for the FR-17 OQ2 replay-fidelity harness.

Run:  python -m pytest eval/replay_fidelity/test_replay_fidelity.py -v
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import corpus  # noqa: E402
import scorer  # noqa: E402
import src_probe  # noqa: E402
import replay_fidelity_check as check  # noqa: E402


# --------------------------------------------------------------------------- #
# Scorer arithmetic
# --------------------------------------------------------------------------- #


def test_spearman_perfect_monotone():
    x = [1, 2, 3, 4, 5]
    y = [10, 20, 30, 40, 50]
    assert scorer.spearman_rho(x, y) == 1.0


def test_spearman_perfect_inverse():
    x = [1, 2, 3, 4, 5]
    y = [50, 40, 30, 20, 10]
    assert scorer.spearman_rho(x, y) == -1.0


def test_spearman_zero_variance_is_zero_not_nan():
    # all-tie predicted -> no rank information -> 0.0, never spuriously 1.0
    rho = scorer.spearman_rho([5, 5, 5, 5], [1, 2, 3, 4])
    assert rho == 0.0


def test_spearman_matches_average_rank_ties():
    # Cross-checked against scipy.stats.spearmanr in the build log (0.86164).
    rho = scorer.spearman_rho([1, 1, 2, 2, 3, 3], [1, 2, 2, 3, 3, 4])
    assert abs(rho - 0.86164) < 1e-3


def test_bootstrap_ci_deterministic():
    pairs = corpus.faithful_corpus()
    pred = [p.proxy for p in pairs]
    obs = [p.truth for p in pairs]
    a = scorer.spearman_bootstrap_ci(pred, obs, iterations=1000)
    b = scorer.spearman_bootstrap_ci(pred, obs, iterations=1000)
    assert a.low == b.low and a.high == b.high  # reproducible


def test_bootstrap_ci_brackets_point():
    pairs = corpus.faithful_corpus()
    pred = [p.proxy for p in pairs]
    obs = [p.truth for p in pairs]
    ci = scorer.spearman_bootstrap_ci(pred, obs, iterations=1000)
    assert ci.low <= ci.point <= ci.high


def test_sign_agreement_and_gap_and_coverage():
    pred = [0.2, -0.1, 0.0, 0.3]
    obs = [0.15, -0.2, 0.0, 0.25]
    assert scorer.sign_agreement(pred, obs) == 1.0
    assert math.isclose(
        scorer.proxy_true_gap(pred, obs),
        (0.05 + 0.1 + 0.0 + 0.05) / 4,
        rel_tol=1e-9,
    )
    # threshold 0.0: promote iff > 0. obs vs pred agree on all four.
    assert scorer.decision_coverage(pred, obs, threshold=0.0) == 1.0


# --------------------------------------------------------------------------- #
# Golden guarantee: faithful passes, every degenerate is rejected
# --------------------------------------------------------------------------- #


def test_faithful_corpus_passes_bar():
    pairs = corpus.faithful_corpus()
    s = scorer.score_fidelity([p.proxy for p in pairs], [p.truth for p in pairs])
    assert s.passed, s.to_dict()


def test_each_degenerate_case_is_rejected():
    for name, (_builder, must_pass) in corpus.GOLDEN_CASES.items():
        if must_pass:
            continue
        pairs = corpus.build_case(name)
        s = scorer.score_fidelity([p.proxy for p in pairs], [p.truth for p in pairs])
        assert not s.passed, f"{name} should be rejected by the OQ2 bar: {s.to_dict()}"


def test_degenerate_cases_vetoed_by_intended_axis():
    expected_axis = {
        "all_tie": "spearman_rho",
        "sign_flipped": "sign_agreement",
        "tiny_window": "window",
        "noise": "spearman_rho",
        "biased_gap": "proxy_true_gap",
    }
    for name, axis in expected_axis.items():
        pairs = corpus.build_case(name)
        s = scorer.score_fidelity([p.proxy for p in pairs], [p.truth for p in pairs])
        vetoed = {c["name"] for c in s.checks if not c["pass"]}
        assert axis in vetoed, f"{name} expected veto by {axis}, got {vetoed}"


# --------------------------------------------------------------------------- #
# Real-shape round trip (SelfModelStore / PolicyOutcome)
# --------------------------------------------------------------------------- #


def test_pairs_roundtrip_through_real_self_model_store():
    pairs = corpus.faithful_corpus()
    store = corpus.pairs_to_store(pairs)
    # The store is the real mnemosyne.self_optimization.SelfModelStore.
    assert type(store).__name__ == "SelfModelStore"
    recovered = corpus.pairs_from_store(store)
    assert len(recovered) == len(pairs)
    # Predicted lift recomputed from counts via the real cf arithmetic matches.
    orig = sorted(p.predicted_lift for p in pairs)
    back = sorted(p.predicted_lift for p in recovered)
    assert all(abs(a - b) < 1e-9 for a, b in zip(orig, back))


def test_predicted_lift_is_real_cf_arithmetic():
    from mnemosyne.learning import counterfactual_replay_score

    pair = corpus._pair_from_counts("x", 5, 8, 20, 0.1)
    assert pair.predicted_lift == counterfactual_replay_score(5, 8, 20)


# --------------------------------------------------------------------------- #
# Honest current-src status + runnable check exit codes
# --------------------------------------------------------------------------- #


def test_current_src_cf_wired_and_fails_closed_until_real_pairs_clear_bar():
    bar = scorer.FidelityBar()
    state = src_probe.probe_current_src(bar)
    assert state["cf_wired_into_gate"] is True
    assert state["shadow_only_by_construction"] is True
    assert state["default_replay_fails_closed"] is True
    assert state["default_promotion_probe"]["promoted"] is False
    assert state["real_paired_corpus_size"] == 0


def test_default_check_passes_because_wired_loop_fails_closed_without_real_pairs():
    # Golden guarantee holds AND wired replay blocks unproven active promotion -> exit 0.
    code = check.main(["--quiet", "--json-out", _tmp("a.json"), "--md-out", _tmp("a.md")])
    assert code == 0


def test_default_report_json_is_strict_json_without_nan_constants():
    out = Path(_tmp("strict.json"))
    code = check.main(["--quiet", "--json-out", str(out), "--md-out", _tmp("strict.md")])
    text = out.read_text(encoding="utf-8")

    assert code == 0
    assert "NaN" not in text
    assert "Infinity" not in text
    assert json.loads(text)["verdict"]["cf_wired_into_gate"] is True


def test_require_wired_fails_until_real_pairs_authorize_promotion():
    # The cf->gate path is wired, but real replay pairs do not yet clear OQ2.
    code = check.main(
        ["--quiet", "--require-wired", "--json-out", _tmp("b.json"), "--md-out", _tmp("b.md")]
    )
    assert code == 2


def _tmp(name: str) -> str:
    out = _HERE.parent / "reports" / "replay_fidelity_test_tmp"
    out.mkdir(parents=True, exist_ok=True)
    return str(out / name)
