"""Drift checks for configuration sources, precedence, and invariant rails.

These operationalize CONFIG-DRIFT-CHECKS.md. Each test either compares the
running code surface against the committed baseline in
``config/drift-baseline.toml`` or asserts an enforced contract behaviorally.

Values and semantics remain owned by the v2 blueprint (§19, §31, §23.5) and the
modules under ``src/mnemosyne``; these tests *detect drift*, they do not redefine
rails, guardrails, or schemas. A failure means the running surface diverged from
the declared baseline — fix the code or mirror the intentional change into the
baseline in the same commit.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from mnemosyne.cli import default_backend
from mnemosyne.policy import OperatingPolicy
from mnemosyne.security import SecurityPolicy
from mnemosyne.self_optimization import (
    PolicyVariant,
    tripwire_check,
    validate_policy_ops_bundle,
    within_invariant_rails,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "config" / "drift-baseline.toml"
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"

_DEFAULT_WEIGHTS = {"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10}


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    with BASELINE_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _in_band_variant(variant_id: str = "v-in-band") -> PolicyVariant:
    return PolicyVariant(
        id=variant_id,
        activation_weights=dict(_DEFAULT_WEIGHTS),
        abstention_threshold=0.45,
        top_k=8,
    )


# --------------------------------------------------------------------------- #
# A. Source-of-truth integrity — the baseline mirrors the live code surface.
# --------------------------------------------------------------------------- #

def test_baseline_rail_names_mirror_policy(baseline: dict[str, Any]) -> None:
    declared = set(baseline["rails"]["required"])
    live = set(OperatingPolicy().immutable_rails)
    assert declared == live, "OperatingPolicy.immutable_rails drifted from the declared baseline"


def test_baseline_security_rails_mirror_security_policy(baseline: dict[str, Any]) -> None:
    declared = set(baseline["rails"]["security"]["required"])
    live = set(SecurityPolicy().immutable_rails)
    assert declared == live, "SecurityPolicy.immutable_rails drifted from the declared baseline"


def test_baseline_tunable_names_exist_on_policy(baseline: dict[str, Any]) -> None:
    policy = OperatingPolicy()
    for name in baseline["tunables"]["names"]:
        assert hasattr(policy, name), f"declared tunable {name!r} is not present on OperatingPolicy"


def test_baseline_tunable_defaults_mirror_policy(baseline: dict[str, Any]) -> None:
    policy = OperatingPolicy()
    for name, declared in baseline["tunables"]["defaults"].items():
        assert getattr(policy, name) == declared, f"tunable default {name!r} drifted from the baseline"
    assert policy.activation_weights == dict(baseline["tunables"]["activation_weights"]), (
        "activation_weights defaults drifted from the baseline"
    )


def test_baseline_authority_contract_mirrors_security_policy(baseline: dict[str, Any]) -> None:
    declared = set(baseline["authority"]["consolidator_only_ops"])
    live = set(SecurityPolicy().consolidator_only_ops)
    assert declared == live, "SecurityPolicy.consolidator_only_ops drifted from the declared baseline"


# --------------------------------------------------------------------------- #
# B. Immutable-rail conformance — enforced at runtime.
# --------------------------------------------------------------------------- #

def test_base_policy_rails_all_enabled() -> None:
    assert all(OperatingPolicy().immutable_rails.values()), "a base-policy immutable rail is disabled"


def test_within_rails_accepts_in_band_variant() -> None:
    assert within_invariant_rails(OperatingPolicy(), _in_band_variant()) is True


def test_numeric_invariant_rails_mirror_policy(baseline: dict[str, Any]) -> None:
    """§31/§23.5 immutable mutation-rate rail VALUES pin live == declared.

    The cold loop tunes WITHIN these and can never widen them, so their numeric
    values are drift-critical (not just their names). A missing declared rail means
    the live policy has drifted from the blueprint baseline; an intentional rename or
    deletion must update ``config/drift-baseline.toml`` in the same commit.
    """
    declared = baseline["rails"]["numeric"]
    policy = OperatingPolicy()
    missing = sorted(name for name in declared if not hasattr(policy, name))
    assert not missing, (
        f"§31 numeric invariant rails declared in the baseline are missing on OperatingPolicy: {missing}; "
        "restore the rails or mirror the intentional contract change into config/drift-baseline.toml"
    )
    present = {name: getattr(policy, name) for name in declared}
    drifted = {
        name: (value, declared[name]) for name, value in present.items() if value != declared[name]
    }
    assert not drifted, (
        f"§31 numeric invariant-rail value drifted from the declared baseline {drifted}; "
        "mirror the intentional change into config/drift-baseline.toml in the same commit"
    )


def test_within_rails_rejects_disabled_rail() -> None:
    policy = OperatingPolicy()
    policy.immutable_rails["tenant_isolation_required"] = False
    assert within_invariant_rails(policy, _in_band_variant()) is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: setattr(v, "top_k", 65),  # above the enforced ceiling
        lambda v: setattr(v, "top_k", 0),  # below the enforced floor
        lambda v: setattr(v, "abstention_threshold", 0.99),  # above the band
        lambda v: setattr(v, "abstention_threshold", 0.01),  # below the band
        lambda v: setattr(v, "activation_weights", {"base_level": 0.5, "semantic": 0.5, "importance": 0.5, "recency": 0.5}),  # sum != 1
        lambda v: setattr(v, "activation_weights", {"base_level": 1.0}),  # key-set mismatch
    ],
)
def test_within_rails_rejects_out_of_band_variant(mutate: Any) -> None:
    variant = _in_band_variant()
    mutate(variant)
    assert within_invariant_rails(OperatingPolicy(), variant) is False


def _ops_bundle(**overrides: Any) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "tenant_id": "tenant-drift",
        "metric": "retrieval_quality",
        "base_policy": {},
        "variants": [
            {
                "id": "variant-shadow",
                "activation_weights": dict(_DEFAULT_WEIGHTS),
                "abstention_threshold": 0.45,
                "top_k": 8,
                "shadow_mode": True,
            }
        ],
        "outcomes": [
            {
                "variant_id": "variant-shadow",
                "reward": 0.6,
                "reward_source": "external_eval",
                "context": {"metric": "retrieval_quality"},
            }
        ],
        "tripwires": [{"id": "tw-1", "diversity": 0.5, "proxy_score": 0.5, "true_score": 0.52}],
        "cadence": {"window_hours": 6.0, "max_updates_per_day": 2},
        "promotion": {"mode": "shadow", "production_mutation": False},
    }
    bundle.update(overrides)
    return bundle


def _finding_codes(result: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in result["findings"]}


def test_ops_validation_flags_disabled_base_rail() -> None:
    rails = dict(OperatingPolicy().immutable_rails)
    rails["tenant_isolation_required"] = False
    result = validate_policy_ops_bundle(_ops_bundle(base_policy={"immutable_rails": rails}))
    assert "base_rail_disabled" in _finding_codes(result)


def test_ops_validation_flags_rail_violating_variant() -> None:
    bundle = _ops_bundle(
        variants=[
            {
                "id": "variant-wide",
                "activation_weights": dict(_DEFAULT_WEIGHTS),
                "abstention_threshold": 0.45,
                "top_k": 999,  # outside the enforced ceiling
                "shadow_mode": True,
            }
        ]
    )
    assert "variant_rail_violation" in _finding_codes(validate_policy_ops_bundle(bundle))


def test_ops_validation_enforces_external_reward_only(baseline: dict[str, Any]) -> None:
    bad = _ops_bundle(
        outcomes=[
            {
                "variant_id": "variant-shadow",
                "reward": 0.6,
                "reward_source": "self_reward",  # not an external source
                "context": {"metric": "retrieval_quality"},
            }
        ]
    )
    assert "invalid_reward_source" in _finding_codes(validate_policy_ops_bundle(bad))
    # The accepted set is exactly what the baseline declares.
    for source in baseline["reward"]["external_sources"]:
        ok = _ops_bundle(
            outcomes=[
                {
                    "variant_id": "variant-shadow",
                    "reward": 0.6,
                    "reward_source": source,
                    "context": {"metric": "retrieval_quality"},
                }
            ]
        )
        assert "invalid_reward_source" not in _finding_codes(validate_policy_ops_bundle(ok))


def test_ops_validation_requires_shadow_promotion() -> None:
    active = _ops_bundle(promotion={"mode": "active", "production_mutation": False})
    assert "promotion_not_shadow" in _finding_codes(validate_policy_ops_bundle(active))
    mutating = _ops_bundle(promotion={"mode": "shadow", "production_mutation": True})
    assert "production_mutation_enabled" in _finding_codes(validate_policy_ops_bundle(mutating))


# --------------------------------------------------------------------------- #
# C. Tunable-parameter drift — defaults sit within the enforced rails.
# --------------------------------------------------------------------------- #

def test_baseline_default_tunables_are_within_rails(baseline: dict[str, Any]) -> None:
    defaults = baseline["tunables"]["defaults"]
    variant = PolicyVariant(
        id="variant-defaults",
        activation_weights=dict(baseline["tunables"]["activation_weights"]),
        abstention_threshold=float(defaults["abstention_threshold"]),
        top_k=int(defaults["top_k"]),
    )
    assert within_invariant_rails(OperatingPolicy(), variant) is True


# --------------------------------------------------------------------------- #
# D. Topology / backing-service selection.
# --------------------------------------------------------------------------- #

def test_default_backend_is_local(baseline: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEME_BACKEND", raising=False)
    assert default_backend() == baseline["topology"]["default_backend"]


def test_backend_env_overrides_default(baseline: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(baseline["topology"]["backend_env"], "postgres")
    assert default_backend() == "postgres"


def test_declared_backends_are_recognized(baseline: dict[str, Any]) -> None:
    assert set(baseline["topology"]["backends"]) == {"local", "postgres"}


# --------------------------------------------------------------------------- #
# E. Credential / authority scope — write authority is role-mediated.
# --------------------------------------------------------------------------- #

def test_agent_role_denied_consolidator_only_ops(baseline: dict[str, Any]) -> None:
    policy = SecurityPolicy()
    for operation in baseline["authority"]["consolidator_only_ops"]:
        decision = policy.authorize_write(operation, role="agent", source_trust_tier=4)
        assert decision.allowed is False, f"agent must not hold write authority for {operation}"
        assert decision.required_role == "consolidator"


def test_consolidator_role_allowed_consolidator_only_ops(baseline: dict[str, Any]) -> None:
    policy = SecurityPolicy()
    for operation in baseline["authority"]["consolidator_only_ops"]:
        decision = policy.authorize_write(operation, role="consolidator", source_trust_tier=4)
        assert decision.allowed is True, f"consolidator should hold write authority for {operation}"


@pytest.mark.parametrize("role", ["agent", "consolidator"])
def test_non_operator_denied_system_prompt_and_policy_sinks(baseline: dict[str, Any], role: str) -> None:
    policy = SecurityPolicy()
    for sink in baseline["authority"]["operator_only_sinks"]:
        decision = policy.authorize_write("write_sink", role=role, source_trust_tier=4, target_sink=sink)  # type: ignore[arg-type]
        assert decision.allowed is False, f"{role} must not write to the {sink} sink"
        assert decision.required_role == "operator"


# --------------------------------------------------------------------------- #
# F. Continuous tripwire signals — model-collapse and reward-hacking guards.
# --------------------------------------------------------------------------- #

def test_tripwire_flags_diversity_collapse() -> None:
    result = tripwire_check(diversity=0.05, proxy_score=0.5, true_score=0.5)
    assert result.passed is False
    assert "diversity" in result.reason


def test_tripwire_flags_reward_hacking_divergence() -> None:
    result = tripwire_check(diversity=0.5, proxy_score=0.95, true_score=0.5)
    assert result.passed is False


def test_tripwire_passes_healthy_signal() -> None:
    assert tripwire_check(diversity=0.5, proxy_score=0.50, true_score=0.52).passed is True


# --------------------------------------------------------------------------- #
# G. Config <-> schema consistency — declared stores exist in the schema.
# --------------------------------------------------------------------------- #

def _schema_tables() -> set[str]:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text))


def test_declared_stores_exist_in_schema(baseline: dict[str, Any]) -> None:
    declared = set(baseline["schema"]["required_tables"])
    actual = _schema_tables()
    missing = declared - actual
    assert not missing, f"declared stores absent from sql/schema.sql (renamed/dropped?): {sorted(missing)}"


def test_no_undocumented_stores(baseline: dict[str, Any]) -> None:
    declared = set(baseline["schema"]["required_tables"])
    actual = _schema_tables()
    undocumented = actual - declared
    assert not undocumented, f"sql/schema.sql has stores not mirrored in the baseline: {sorted(undocumented)}"
