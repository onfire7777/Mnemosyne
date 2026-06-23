"""Blueprint-parity invariant tests for the CC-LS lane.

This suite locks the *invariants* the Mnemosyne v2 blueprint places on the
learning / self-optimization / parametric tiers (Phases 4 & 5). The behavioural
happy-paths of these modules are exercised elsewhere; here we pin the safety
rails and validation finding-codes that must never silently regress:

* self-optimization stays *shadow-first* and inside immutable rails,
* the policy-ops bundle validator fails closed on every rail it guards,
* the parametric tier only mutates under external reward + monotonic trust and
  never lets untrusted data reach the system prompt,
* the parametric artifact store refuses path traversal,
* the command-backed trainer boundary fails closed on bad provider output.

These are deterministic and require no live infrastructure.
"""

from __future__ import annotations

import copy
import sys

import pytest

from mnemosyne.eval import assert_seed_suite_passes, run_seed_suite
from mnemosyne.learning import LearningSystem, Trajectory
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.parametric import (
    CommandParametricTrainer,
    ParametricArtifact,
    ParametricArtifactStore,
    ParametricInvariantRails,
    ParametricTier,
)
from mnemosyne.learning import Lesson, Procedure
from mnemosyne.policy import OperatingPolicy
from mnemosyne.self_optimization import (
    ContextualBanditLearner,
    PolicyVariant,
    SelfModelStore,
    policy_ops_fingerprint,
    policy_variant_from_dict,
    validate_policy_ops_bundle,
    within_invariant_rails,
)

TENANT = "tenant-parity"


# --------------------------------------------------------------------------- #
# self_optimization: invariant rails + deterministic bandit                   #
# --------------------------------------------------------------------------- #

def _base_weights() -> dict[str, float]:
    return {"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10}


def test_within_invariant_rails_accepts_valid_variant_and_rejects_violations() -> None:
    base = OperatingPolicy()
    valid = PolicyVariant(id="ok", activation_weights=_base_weights(), abstention_threshold=0.45, top_k=8)
    assert within_invariant_rails(base, valid) is True

    # top_k outside [1, 64]
    assert within_invariant_rails(base, PolicyVariant("z", _base_weights(), 0.45, 0)) is False
    assert within_invariant_rails(base, PolicyVariant("z", _base_weights(), 0.45, 100)) is False
    # abstention outside [0.05, 0.95]
    assert within_invariant_rails(base, PolicyVariant("z", _base_weights(), 0.99, 8)) is False
    # activation weights must sum to 1.0
    skewed = {"base_level": 0.5, "semantic": 0.5, "importance": 0.20, "recency": 0.10}
    assert within_invariant_rails(base, PolicyVariant("z", skewed, 0.45, 8)) is False
    # activation weight keys must match the base policy exactly
    wrong_keys = {"base_level": 0.5, "semantic": 0.5}
    assert within_invariant_rails(base, PolicyVariant("z", wrong_keys, 0.45, 8)) is False


def test_within_invariant_rails_requires_all_immutable_rails_enabled() -> None:
    base = OperatingPolicy()
    base.immutable_rails["tenant_isolation_required"] = False
    valid = PolicyVariant(id="ok", activation_weights=_base_weights(), abstention_threshold=0.45, top_k=8)
    # A structurally-valid variant must still be rejected when a rail is disabled.
    assert within_invariant_rails(base, valid) is False


def test_contextual_bandit_is_deterministic_and_bounds_reward() -> None:
    store = SelfModelStore()
    bandit = ContextualBanditLearner(store)
    ctx = {"metric": "retrieval_quality"}
    # Reward is clamped into [0, 1] regardless of the raw signal.
    bandit.record_outcome(TENANT, "a", 2.0, context=ctx)
    bandit.record_outcome(TENANT, "a", 0.9, context=ctx)
    bandit.record_outcome(TENANT, "b", 0.1, context=ctx)
    stored = store.outcomes(TENANT, ctx)
    assert max(o.reward for o in stored) <= 1.0

    variants = [
        PolicyVariant("a", _base_weights(), 0.45, 8),
        PolicyVariant("b", _base_weights(), 0.45, 8),
    ]
    # Same evidence -> same choice every time (no hidden randomness).
    first = bandit.choose_variant(TENANT, variants, ctx)
    second = bandit.choose_variant(TENANT, variants, ctx)
    assert first.id == second.id == "a"


def test_choose_variant_rejects_empty_candidate_set() -> None:
    bandit = ContextualBanditLearner(SelfModelStore())
    with pytest.raises(ValueError):
        bandit.choose_variant(TENANT, [], {"metric": "retrieval_quality"})


def test_policy_variant_from_dict_requires_activation_weights() -> None:
    row = {"id": "v", "abstention_threshold": 0.45, "top_k": 8}
    with pytest.raises(ValueError):
        policy_variant_from_dict(row)
    parsed = policy_variant_from_dict({**row, "activation_weights": _base_weights()})
    assert parsed.id == "v" and parsed.top_k == 8


def test_policy_ops_fingerprint_is_stable_and_key_order_independent() -> None:
    a = {"tenant_id": "t", "metric": "retrieval_quality", "variants": []}
    b = {"variants": [], "metric": "retrieval_quality", "tenant_id": "t"}
    fp = policy_ops_fingerprint(a)
    assert fp == policy_ops_fingerprint(b)
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)


# --------------------------------------------------------------------------- #
# self_optimization: validate_policy_ops_bundle fails closed on every rail    #
# --------------------------------------------------------------------------- #

def _valid_bundle() -> dict:
    return {
        "tenant_id": TENANT,
        "metric": "retrieval_quality",
        "variants": [
            {
                "id": "variant-stable",
                "activation_weights": _base_weights(),
                "abstention_threshold": 0.45,
                "top_k": 8,
                "shadow_mode": True,
            },
            {
                "id": "variant-recall",
                "activation_weights": {"base_level": 0.25, "semantic": 0.45, "importance": 0.20, "recency": 0.10},
                "abstention_threshold": 0.50,
                "top_k": 12,
                "shadow_mode": True,
            },
        ],
        "outcomes": [
            {"variant_id": "variant-stable", "reward": 0.70, "reward_source": "external_eval"},
            {"variant_id": "variant-recall", "reward": 0.80, "reward_source": "external_eval"},
            {"variant_id": "variant-recall", "reward": 0.75, "reward_source": "external_eval"},
        ],
        "tripwires": [
            {"id": "tw-1", "diversity": 0.5, "proxy_score": 0.86, "true_score": 0.80},
        ],
        "cadence": {"window_hours": 24.0, "max_updates_per_day": 2},
        "promotion": {"mode": "shadow", "production_mutation": False},
    }


def _codes(result: dict) -> set[str]:
    return {finding["code"] for finding in result["findings"]}


def test_valid_policy_ops_bundle_passes_clean() -> None:
    result = validate_policy_ops_bundle(_valid_bundle())
    assert result["ok"] is True, result["findings"]
    assert result["findings"] == []
    assert result["summary"]["recommended_variant_id"] in {"variant-stable", "variant-recall"}
    assert len(result["fingerprint"]) == 64


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda b: b["variants"][0].__setitem__("shadow_mode", False), "variant_not_shadow"),
        (lambda b: b["outcomes"][0].__setitem__("reward_source", "internal"), "invalid_reward_source"),
        (lambda b: b["promotion"].__setitem__("mode", "live"), "promotion_not_shadow"),
        (lambda b: b["promotion"].__setitem__("production_mutation", True), "production_mutation_enabled"),
        (lambda b: b["cadence"].__setitem__("window_hours", 0.25), "cadence_window_too_short"),
        (lambda b: b["cadence"].__setitem__("max_updates_per_day", 99), "cadence_updates_too_frequent"),
        (lambda b: b["variants"][0].__setitem__("top_k", 1000), "variant_rail_violation"),
        (lambda b: b["promotion"].__setitem__("expected_recommended_variant_id", "nope"), "recommended_variant_mismatch"),
        (lambda b: b.__setitem__("variants", b["variants"][:1]), "insufficient_variants"),
        (lambda b: b.__setitem__("outcomes", b["outcomes"][:2]), "insufficient_outcomes"),
    ],
)
def test_policy_ops_bundle_fails_closed_on_each_rail(mutate, expected_code: str) -> None:
    bundle = copy.deepcopy(_valid_bundle())
    mutate(bundle)
    result = validate_policy_ops_bundle(bundle)
    assert result["ok"] is False
    assert expected_code in _codes(result)


# --------------------------------------------------------------------------- #
# parametric: immutable rails, artifact store, command trainer                #
# --------------------------------------------------------------------------- #

def test_parametric_rails_accept_compliant_proposal() -> None:
    rails = ParametricInvariantRails()
    artifact = ParametricArtifact(
        tenant_id=TENANT,
        source_ids=["lesson-1"],
        adapter_kind="local-shadow-adapter",
        metrics={"mutation_rate": 0.01, "prune_fraction": 0.0},
    )
    report = rails.proposal_report(
        artifact,
        {"metadata": {"reward_signal": "external_only", "monotonic_trust": True}},
    )
    assert report["reward_signal"] == "external_only"
    assert report["provider_metadata_checked"] is True


@pytest.mark.parametrize(
    ("metrics", "metadata"),
    [
        ({"mutation_rate": 0.9}, {}),  # mutation rate exceeds rail bound
        ({"prune_fraction_per_pass": 0.9}, {}),  # prune fraction exceeds rail bound
        ({}, {"reward_signal": "internal"}),  # reward must be external-only
        ({}, {"monotonic_trust": False}),  # trust must be monotonic
        ({}, {"trust_tier_delta": -1}),  # trust tier may not widen
        ({}, {"target_sink": "system_prompt"}),  # untrusted->system-prompt forbidden
        ({}, {"untrusted_to_system_prompt": True}),
        ({}, {"eval_source_overlap": True}),  # training data may not overlap eval suite
    ],
)
def test_parametric_rails_fail_closed_on_violations(metrics: dict, metadata: dict) -> None:
    rails = ParametricInvariantRails()
    artifact = ParametricArtifact(TENANT, ["lesson-1"], "k", metrics=dict(metrics))
    with pytest.raises(ValueError):
        rails.proposal_report(artifact, {"metadata": metadata})


def test_parametric_tier_proposal_uses_only_active_validated_sources() -> None:
    tier = ParametricTier()  # no trainer -> deterministic local shadow adapter
    lessons = [
        Lesson(tenant_id=TENANT, lesson_type="corrective", failure_signature="sig", content="x", status="active"),
        Lesson(tenant_id=TENANT, lesson_type="corrective", failure_signature="sig2", content="y", status="candidate"),
    ]
    procedures = [
        Procedure(tenant_id=TENANT, kind="checklist", name="p", body="b", signature={}, status="validated"),
        Procedure(tenant_id=TENANT, kind="checklist", name="p2", body="b", signature={}, status="candidate"),
    ]
    artifact = tier.propose_from_lessons(TENANT, lessons, procedures)
    assert artifact.adapter_kind == "local-shadow-adapter"
    assert artifact.status == "shadow"
    # only the active lesson and validated procedure feed the adapter candidate
    assert len(artifact.source_ids) == 2
    assert lessons[1].id not in artifact.source_ids
    assert procedures[1].id not in artifact.source_ids


def test_parametric_artifact_store_roundtrips_and_blocks_traversal(tmp_path) -> None:
    store = ParametricArtifactStore(tmp_path)
    artifact = ParametricArtifact(TENANT, ["lesson-1"], "local-shadow-adapter")
    uri = store.write(artifact, {"phase": "proposal"})
    loaded = store.load_artifact(uri)
    assert loaded.id == artifact.id and loaded.tenant_id == TENANT
    # path traversal in tenant / artifact id segments is refused
    with pytest.raises(ValueError):
        store.write(ParametricArtifact("../escape", ["l"], "k"))
    with pytest.raises(ValueError):
        store._path_for("ok", "../escape")


def test_command_parametric_trainer_validates_construction_and_provider_output() -> None:
    with pytest.raises(ValueError):
        CommandParametricTrainer("")  # empty command rejected

    py = sys.executable

    bad_json = CommandParametricTrainer([py, "-c", "print('not json')"])
    with pytest.raises(ValueError):
        bad_json.propose(TENANT, [], [], ["s"], ["rail"])

    nonzero = CommandParametricTrainer([py, "-c", "import sys; sys.exit(2)"])
    with pytest.raises(ValueError):
        nonzero.propose(TENANT, [], [], ["s"], ["rail"])

    ok = CommandParametricTrainer([py, "-c", "import json; print(json.dumps({'adapter_kind': 'remote-lora'}))"])
    assert ok.propose(TENANT, [], [], ["s"], ["rail"]) == {"adapter_kind": "remote-lora"}


# --------------------------------------------------------------------------- #
# policy + eval + learning edge cases                                         #
# --------------------------------------------------------------------------- #

def test_operating_policy_from_dict_backcompat_and_rails_default() -> None:
    default = OperatingPolicy.from_dict(None)
    assert all(default.immutable_rails.values())
    # legacy "min_trust_tier" maps onto max_trust_tier
    mapped = OperatingPolicy.from_dict({"min_trust_tier": 2})
    assert mapped.max_trust_tier == 2
    # unknown keys are ignored rather than crashing
    ignored = OperatingPolicy.from_dict({"not_a_real_knob": 5, "top_k": 11})
    assert ignored.top_k == 11
    assert not hasattr(ignored, "not_a_real_knob")


def test_eval_seed_suite_passes_every_case() -> None:
    outcomes = run_seed_suite()
    assert outcomes, "seed suite must contain regression cases"
    assert all(o.passed for o in outcomes), [o.name for o in outcomes if not o.passed]
    # the strict gate must not raise when the suite is green
    assert_seed_suite_passes()


def test_failure_attribution_without_failed_step_is_low_confidence() -> None:
    learning = LearningSystem(LocalMemoryEngine())
    trajectory = Trajectory(
        tenant_id=TENANT,
        user_id="user-parity",
        session_id="s",
        task="ambiguous task",
        steps=[{"name": "step", "status": "ok"}],
        outcome="failure",
        reward=-1.0,
        memory_version="v1",
    )
    attribution = learning.attribute_failure(learning.log_trajectory(trajectory))
    assert attribution.cause == "outcome marked failure without failed step"
    assert attribution.confidence == pytest.approx(0.45)
