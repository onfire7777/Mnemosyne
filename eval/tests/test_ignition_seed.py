"""Tests for the OQ5 suite-ignition curated seed set (FR-14 / FR-17).

Proves the seed set loads into RegressionCase-shaped objects, the origin tagging
is well-formed, and the ignition-status reporter correctly flips to ACTIVE at
N_active>=30 (curated+genuine only, synthetic excluded and capped).
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))

from eval.ignition_seed import (  # noqa: E402
    N_ACTIVE,
    compute_ignition_status,
    load_seed_cases,
    regression_cases,
)
from eval.ignition_seed.ignition_status import (  # noqa: E402
    MIN_CURATED,
    MIN_GENUINE,
    render_markdown,
)
from mnemosyne.gate import PromotionGate, RegressionCase  # noqa: E402


def test_cases_load_as_regression_case_objects():
    cases = regression_cases()
    assert cases, "seed set must be non-empty"
    for c in cases:
        assert isinstance(c, RegressionCase)
        assert c.id and c.signature and c.query and c.expected_substring
        assert c.tier in {"smoke", "core", "archive"}


def test_every_case_tagged_with_valid_origin():
    loaded = load_seed_cases()
    for lc in loaded:
        assert lc.origin in {"curated", "genuine", "synthetic"}


def test_no_duplicate_ids():
    ids = [lc.id for lc in load_seed_cases()]
    assert len(ids) == len(set(ids))


def test_slice_floors_met():
    status = compute_ignition_status()
    assert status.counts["curated"] >= MIN_CURATED, status.counts
    assert status.counts["genuine"] >= MIN_GENUINE, status.counts
    # all protected tiers present
    assert status.protected_active + status.protected_synthetic > 0


def test_n_active_excludes_synthetic_and_ignites():
    status = compute_ignition_status()
    # N_active is curated + genuine only.
    assert status.n_active == status.counts["curated"] + status.counts["genuine"]
    # Synthetic does NOT contribute to the active count.
    assert status.n_active < sum(status.counts.values())
    # Seed set is sized to actually ignite.
    assert status.n_active >= N_ACTIVE
    assert status.mode == "ACTIVE"
    assert status.ready is True
    assert status.blocking_reasons == []


def test_synthetic_cap_respected():
    status = compute_ignition_status()
    # synthetic <= 2x curated (never counted, but bounded).
    assert status.synthetic_within_cap, (status.counts, status.synthetic_cap)


def test_shadow_when_threshold_raised_above_active():
    # Raise the bar above what the curated+genuine slices can supply -> SHADOW.
    status = compute_ignition_status(n_active_target=10_000)
    assert status.mode == "SHADOW"
    assert status.ready is False
    assert any("N_active" in r for r in status.blocking_reasons)


def test_loaded_cases_feed_promotion_gate():
    """The RegressionCase objects are exactly what PromotionGate accepts."""
    cases = regression_cases()

    class _Engine:
        branches: dict = {}

    gate = PromotionGate(engine=_Engine(), cases=cases)
    assert gate.cases is cases
    assert len(gate.cases) == len(cases)


def test_origin_forward_compat_with_future_dataclass():
    """If RegressionCase gains an 'origin' field, the loader passes it through;
    if not (current shape), it is stripped and still carried by LoadedCase."""
    field_names = {f.name for f in dataclasses.fields(RegressionCase)}
    loaded = load_seed_cases()
    if "origin" in field_names:
        # Future shape: origin must round-trip onto the dataclass.
        for lc in loaded:
            assert getattr(lc.case, "origin") == lc.origin
    else:
        # Current shape: origin is not on the dataclass but is carried alongside.
        assert all(lc.origin for lc in loaded)


def test_render_markdown_smoke():
    md = render_markdown(compute_ignition_status())
    assert "OQ5 Suite-Ignition Readiness" in md
    assert "ACTIVE" in md


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
