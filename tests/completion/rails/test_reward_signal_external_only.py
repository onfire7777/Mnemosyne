"""§31 RAIL 5 — reward_signal external_only.

Rail: "optimizer cannot edit reward/verifier/eval suite." Operationally this
means (a) the optimizer's reward must come from an external source, never a
self-generated proxy, and (b) the optimizer's training sources must not overlap
the evaluation suite.

Enforcement points (BOTH enforced):
- ``ParametricInvariantRails.proposal_report`` (parametric.py:133-144) raises if
  provider metadata sets ``reward_signal`` to anything but ``external_only`` or if
  ``eval_source_overlap`` is True.
- ``validate_policy_ops_bundle`` (self_optimization.py:376-379) rejects any
  outcome whose ``reward_source`` is not in
  {external_eval, human_feedback, protected_suite}.

These tests try to feed a self-generated reward through each surface and assert
refusal.
"""

from __future__ import annotations

import pytest

from mnemosyne.parametric import ParametricArtifact, ParametricInvariantRails
from mnemosyne.self_optimization import validate_policy_ops_bundle


# --- Surface A: parametric proposal gate --------------------------------------

def test_parametric_reward_signal_must_be_external_only():
    rails = ParametricInvariantRails()
    artifact = ParametricArtifact(
        tenant_id="tenant-rails",
        source_ids=["lesson-1"],
        adapter_kind="local-shadow-adapter",
    )
    with pytest.raises(ValueError, match="reward_signal must be external_only"):
        rails.proposal_report(artifact, {"metadata": {"reward_signal": "self_generated"}})


def test_parametric_optimizer_cannot_train_on_eval_suite():
    rails = ParametricInvariantRails()
    artifact = ParametricArtifact(
        tenant_id="tenant-rails",
        source_ids=["lesson-1"],
        adapter_kind="local-shadow-adapter",
    )
    with pytest.raises(ValueError, match="overlaps evaluation suite"):
        rails.proposal_report(artifact, {"metadata": {"eval_source_overlap": True}})


# --- Surface B: policy-ops bundle validation ----------------------------------

def _base_bundle() -> dict:
    weights = {"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10}
    variant = {
        "id": "v1",
        "activation_weights": dict(weights),
        "abstention_threshold": 0.4,
        "top_k": 8,
        "shadow_mode": True,
    }
    variant2 = {**variant, "id": "v2"}
    return {
        "tenant_id": "tenant-rails",
        "metric": "retrieval_quality",
        "variants": [variant, variant2],
        "tripwires": [{"id": "t1", "diversity": 0.5, "proxy_score": 0.6, "true_score": 0.6}],
        "cadence": {"window_hours": 2.0, "max_updates_per_day": 2},
        "promotion": {"mode": "shadow", "production_mutation": False},
    }


def test_policy_ops_rejects_self_generated_reward_source():
    bundle = _base_bundle()
    bundle["outcomes"] = [
        {"variant_id": "v1", "reward": 0.9, "reward_source": "self_generated"},
        {"variant_id": "v2", "reward": 0.5, "reward_source": "self_generated"},
        {"variant_id": "v1", "reward": 0.8, "reward_source": "self_generated"},
    ]
    report = validate_policy_ops_bundle(bundle)
    codes = {f["code"] for f in report["findings"]}
    assert "invalid_reward_source" in codes
    assert report["ok"] is False


def test_policy_ops_accepts_external_reward_source():
    bundle = _base_bundle()
    bundle["outcomes"] = [
        {"variant_id": "v1", "reward": 0.9, "reward_source": "external_eval"},
        {"variant_id": "v2", "reward": 0.5, "reward_source": "human_feedback"},
        {"variant_id": "v1", "reward": 0.8, "reward_source": "protected_suite"},
    ]
    report = validate_policy_ops_bundle(bundle)
    codes = {f["code"] for f in report["findings"]}
    assert "invalid_reward_source" not in codes
