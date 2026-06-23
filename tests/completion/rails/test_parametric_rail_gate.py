"""§31 rails — enforcement at the parametric-tier promotion gate.

``ParametricInvariantRails`` (src/mnemosyne/parametric.py) is the single place
in the tree where several §31 rails are *structurally* enforced: a proposed
adapter artifact is rejected if its reported metrics or provider metadata try to
widen a rail. These tests drive each breach through the real
``ParametricInvariantRails.proposal_report`` / ``ParametricTier.propose_from_lessons``
path and assert the system raises / refuses.

Blueprint: §31 invariant rails (7); G7 safe-by-construction.

NOTE on scope: this gate only sees *self-reported* metrics. It is a necessary
but not sufficient enforcement point for the rate rails (supersession_rate,
prune_fraction): a component that actually performs supersession/pruning
(engine.upsert_assertion, consolidation._run_forgetter) is not forced to report
honest metrics into this gate. The live-path gaps are covered (and xfailed)
in test_supersession_rate.py and test_prune_fraction.py.
"""

from __future__ import annotations

import pytest

from mnemosyne.learning import Lesson, Procedure
from mnemosyne.parametric import (
    ParametricArtifact,
    ParametricInvariantRails,
    ParametricTier,
)


# --- rail bound constants, asserted to match the blueprint exactly ------------

def test_rail_constants_match_blueprint_section_31():
    rails = ParametricInvariantRails()
    assert rails.max_supersession_rate == 0.05
    assert rails.max_prune_fraction_per_pass == 0.02
    assert rails.reward_signal == "external_only"
    assert rails.monotonic_trust is True
    assert rails.untrusted_to_system_prompt == "forbidden"


def _artifact(metrics: dict[str, float] | None = None) -> ParametricArtifact:
    return ParametricArtifact(
        tenant_id="tenant-rails",
        source_ids=["lesson-1"],
        adapter_kind="local-shadow-adapter",
        metrics=dict(metrics or {}),
    )


# --- RAIL 1: max_supersession_rate 0.05 (parametric metrics view) -------------

def test_supersession_rate_over_limit_is_refused():
    rails = ParametricInvariantRails()
    artifact = _artifact({"supersession_rate": 0.051})
    with pytest.raises(ValueError, match="supersession_rate exceeds"):
        rails.proposal_report(artifact, provider={})


def test_supersession_rate_at_limit_is_allowed():
    rails = ParametricInvariantRails()
    artifact = _artifact({"supersession_rate": 0.05})
    report = rails.proposal_report(artifact, provider={})
    assert report["bounds"]["max_supersession_rate"] == 0.05


# --- RAIL 3: max_prune_fraction_per_pass 0.02 (parametric metrics view) -------

@pytest.mark.parametrize("key", ["prune_fraction", "prune_fraction_per_pass"])
def test_prune_fraction_over_limit_is_refused(key: str):
    rails = ParametricInvariantRails()
    artifact = _artifact({key: 0.021})
    with pytest.raises(ValueError, match="exceeds 0.02"):
        rails.proposal_report(artifact, provider={})


def test_prune_fraction_at_limit_is_allowed():
    rails = ParametricInvariantRails()
    artifact = _artifact({"prune_fraction": 0.02})
    rails.proposal_report(artifact, provider={})  # must not raise


# --- RAIL 5: reward_signal external_only --------------------------------------

def test_reward_signal_cannot_be_changed_from_external_only():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    provider = {"metadata": {"reward_signal": "self_generated"}}
    with pytest.raises(ValueError, match="reward_signal must be external_only"):
        rails.proposal_report(artifact, provider)


def test_reward_signal_external_only_passes():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    rails.proposal_report(artifact, {"metadata": {"reward_signal": "external_only"}})


# --- RAIL 4: monotonic_trust --------------------------------------------------

def test_monotonic_trust_cannot_be_disabled_via_metadata():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    with pytest.raises(ValueError, match="monotonic_trust cannot be disabled"):
        rails.proposal_report(artifact, {"metadata": {"monotonic_trust": False}})


def test_trust_tier_cannot_be_widened():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    with pytest.raises(ValueError, match="trust tier cannot be widened"):
        rails.proposal_report(artifact, {"metadata": {"trust_tier_delta": -1}})


# --- RAIL 6: untrusted_to_system_prompt forbidden -----------------------------

def test_untrusted_target_sink_system_prompt_is_forbidden():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    with pytest.raises(ValueError, match="untrusted_to_system_prompt is forbidden"):
        rails.proposal_report(artifact, {"metadata": {"target_sink": "system_prompt"}})


def test_untrusted_to_system_prompt_flag_is_forbidden():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    with pytest.raises(ValueError, match="untrusted_to_system_prompt is forbidden"):
        rails.proposal_report(artifact, {"metadata": {"untrusted_to_system_prompt": True}})


# --- RAIL 5 corollary: optimizer cannot train on the eval suite ---------------

def test_eval_source_overlap_is_refused():
    rails = ParametricInvariantRails()
    artifact = _artifact()
    with pytest.raises(ValueError, match="overlaps evaluation suite"):
        rails.proposal_report(artifact, {"metadata": {"eval_source_overlap": True}})


# --- End-to-end: ParametricTier carries the immutable rail labels -------------

def test_parametric_tier_attaches_immutable_rail_labels():
    """A proposed artifact must carry the immutable rail labels so the
    downstream gate (ParametricTier.evaluate) can require them."""

    tier = ParametricTier()
    lesson = Lesson(
        tenant_id="tenant-rails",
        lesson_type="safety",
        failure_signature="rail-widening-attempt",
        content="never widen a rail",
        status="active",
    )
    procedure = Procedure(
        tenant_id="tenant-rails",
        kind="check",
        name="rail-bound-procedure",
        body="check rails",
        signature={"inputs": [], "outputs": []},
        status="active",
    )
    artifact = tier.propose_from_lessons("tenant-rails", [lesson], [procedure])
    required = set(ParametricInvariantRails().labels())
    assert required.issubset(set(artifact.immutable_rails))
    # Required rails include the three §31 names the parametric gate owns.
    assert "monotonic_trust_required" in artifact.immutable_rails
    assert "external_reward_signal_required" in artifact.immutable_rails
    assert "untrusted_to_system_prompt_forbidden" in artifact.immutable_rails
