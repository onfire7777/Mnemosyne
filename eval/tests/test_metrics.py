"""Unit tests for the harness metric primitives (no Mnemosyne dependency)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.harness import metrics  # noqa: E402


def test_recall_at_k_basic():
    assert metrics.recall_at_k(["a", "b", "c"], ["a"], 3) == 1.0
    assert metrics.recall_at_k(["x", "b", "c"], ["a"], 3) == 0.0
    assert metrics.recall_at_k(["a", "b"], ["a", "b"], 1) == 0.5
    assert metrics.recall_at_k([], ["a"], 5) == 0.0
    assert metrics.recall_at_k(["a"], [], 5) == 0.0  # no relevant -> 0


def test_ndcg_perfect_and_worst():
    # Perfect ranking -> 1.0
    assert metrics.ndcg_at_k(["a", "b", "c"], ["a"], 3) == 1.0
    # Relevant item at rank 3 vs rank 1 -> < 1.0 but > 0
    nd = metrics.ndcg_at_k(["x", "y", "a"], ["a"], 3)
    assert 0.0 < nd < 1.0
    # Not retrieved -> 0
    assert metrics.ndcg_at_k(["x", "y"], ["a"], 2) == 0.0


def test_percentile_interpolation():
    vals = [1, 2, 3, 4, 5]
    assert metrics.percentile(vals, 0.5) == 3
    assert metrics.percentile(vals, 0.0) == 1
    assert metrics.percentile(vals, 1.0) == 5
    # P95 of 1..100 should be ~95
    assert abs(metrics.percentile(list(range(1, 101)), 0.95) - 95.05) < 0.1


def test_latency_summary_empty():
    s = metrics.latency_summary([])
    assert s.count == 0 and math.isnan(s.p95)


def test_ece_perfectly_calibrated_is_zero():
    # 10 items at confidence 1.0 all correct, 10 at 0.0 all wrong -> ECE 0
    confs = [1.0] * 10 + [0.0] * 10
    correct = [True] * 10 + [False] * 10
    res = metrics.expected_calibration_error(confs, correct, n_bins=10)
    assert res.ece < 1e-9


def test_ece_overconfident_is_positive():
    # confidence 0.9 but only 50% correct -> ECE ~0.4
    confs = [0.9] * 10
    correct = [True] * 5 + [False] * 5
    res = metrics.expected_calibration_error(confs, correct, n_bins=10)
    assert 0.35 < res.ece < 0.45


def test_wilson_interval_bounds():
    ci = metrics.wilson_interval(10, 10)
    assert ci.point == 1.0
    assert ci.high <= 1.0 and ci.low < 1.0  # Wilson never gives a degenerate [1,1]
    ci0 = metrics.wilson_interval(0, 10)
    assert ci0.point == 0.0 and ci0.low >= 0.0


def test_bootstrap_is_deterministic():
    vals = [0.1, 0.5, 0.9, 0.2, 0.8, 0.3]
    a = metrics.bootstrap_mean_interval(vals, iterations=500)
    b = metrics.bootstrap_mean_interval(vals, iterations=500)
    assert a.low == b.low and a.high == b.high  # same seed -> identical CI


def test_bootstrap_percentile_interval_brackets_point():
    vals = [float(x) for x in range(1, 51)]
    ci = metrics.bootstrap_percentile_interval(vals, 0.95, iterations=500)
    assert ci.low <= ci.point <= ci.high
