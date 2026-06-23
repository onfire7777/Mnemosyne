"""Tests for the per-memory-type calibration eval (FR-6 / §16 ECE / OQ4).

These drive the REAL engine through the public CLI (slower: CLI subprocesses) and
assert the calibration runner produces real, well-formed ECE / reliability / Brier
numbers and the Codex-reconciliation handoff structure. They follow the same
public-CLI-only contract as ``eval/tests/test_harness_integration.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_CAL_DIR = _HERE.parent
_EVAL_DIR = _HERE.parents[1]
_REPO = _HERE.parents[2]
for p in (str(_REPO), str(_EVAL_DIR), str(_CAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import dataset as ds  # noqa: E402
import runner as cal_runner  # noqa: E402


def test_dataset_spans_all_memory_types_and_both_labels():
    snap = ds.to_dict()
    assert set(snap["memory_types"]) == set(ds.MEMORY_TYPES)
    assert len(ds.MEMORY_TYPES) >= 5
    for mt, block in snap["sets"].items():
        counts = block["counts"]
        # Every memory type must carry BOTH answerable and unanswerable items so a
        # per-type calibration set has correct + incorrect mass to tune against.
        assert counts["answerable"] >= 3, mt
        assert counts["unanswerable"] >= 3, mt
        assert counts["corpus"] >= 4, mt
    assert snap["totals"]["answerable"] > 0
    assert snap["totals"]["unanswerable"] > 0


def test_probe_labels_are_consistent():
    for p in ds.all_probes():
        if p.answerable:
            assert p.gold_substr, f"answerable probe {p.probe_id} needs a gold_substr"
            assert p.gold_substr == p.gold_substr.lower()
        else:
            assert p.gold_substr is None, f"unanswerable probe {p.probe_id} must have no gold"
        assert p.band in {"clear", "near", "hard-negative", "poison"}


@pytest.mark.slow
def test_runner_produces_real_ece_and_handoff():
    report = cal_runner.run(write=False, dump_json=False)

    # Real, bounded ECE under BOTH threshold regimes.
    for regime in ("policy_threshold", "conformal_threshold"):
        ece = report["ece"][regime]["overall"]
        brier = report["ece"][regime]["brier"]
        assert 0.0 <= ece <= 1.0, regime
        assert 0.0 <= brier <= 1.0, regime
        per_type = report["ece"][regime]["per_memory_type"]
        assert set(per_type) == set(ds.MEMORY_TYPES)
        for mt, v in per_type.items():
            assert 0.0 <= v <= 1.0, (regime, mt)

    # Reliability diagram present with 10 bins on each regime.
    for regime in ("policy_threshold", "conformal_threshold"):
        bins = report["reliability_diagram"][regime]
        assert len(bins) == 10
        # Bin counts sum to the full probe set.
        assert sum(b["count"] for b in bins) == report["totals"]["probes"]

    # Codex handoff: per-type {confidence, correct} lists exist and are well-formed.
    handoff = report["codex_reconciliation"]["calibration_examples"]
    assert set(handoff) == set(ds.MEMORY_TYPES)
    for mt, examples in handoff.items():
        assert examples, mt
        for ex in examples:
            assert set(ex) == {"confidence", "correct"}
            assert 0.0 <= ex["confidence"] <= 1.0
            assert isinstance(ex["correct"], bool)

    # Root-cause diagnostic is present.
    sig = report["confidence_signal"]
    assert "degenerate_signal" in sig
    assert isinstance(sig["degenerate_signal"], bool)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
