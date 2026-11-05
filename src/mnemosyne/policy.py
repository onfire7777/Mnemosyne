"""Operating policy and invariant rails."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any

LEARNING_COMPONENTS = (
    'routes',
    'skills',
    'items',
    'lessons',
    'three_factor',
    'adaptive_rates',
    'stiffness',
    'deferred_resolution',
    'reconsolidation',
    'pattern_separation',
    'schema',
    'homeostasis',
    'revalidation',
    'dreamer',
    'contingency',
    'curiosity',
    'exploration',
    'fast_path',
    'chunking',
    'insight',
    'metacognition',
    'selective_import',
)
LEARNING_RAILS = (
    'learning_reward_external_only',
    'learning_salience_only',
    'learning_after_access_policy',
    'learning_changes_reversible',
    'learning_bounded_steps',
    'labile_updates_are_new_revisions',
    'learning_freeze_on_regression',
    'learning_tenant_scoped',
    'learned_effects_need_approval',
    'erasure_cascades_to_learning',
    'credit_requires_contingency',
    'no_use_only_strengthening',
    'exploration_never_zero',
    'symmetric_updates',
    'goal_check_on_every_serve',
    'reward_sources_allowlisted',
    'replay_requires_new_evidence',
    'scope_grows_by_evidence_only',
    'retired_stays_retired',
    'evidence_never_labile',
    'predictions_write_once',
    'slow_store_revisions_only',
    'single_learning_write_path',
    'learning_failures_are_defects',
)

CONSOLIDATION_CADENCE_TIERS = ("fast", "medium", "slow")
_DEFAULT_CADENCE_TIER_PASSES: dict[str, tuple[str, ...]] = {
    "fast": ("replayer", "summarizer", "embedder"),
    "medium": ("replayer", "extractor", "resolver", "belief_reviser", "promotion_gate"),
    "slow": (
        "replayer",
        "lesson_distiller",
        "skill_inducer",
        "forgetter",
        "user_model_updater",
        "learning_reflect",
    ),
}
_DEFAULT_CADENCE_TIER_MIN_STEPS: dict[str, int] = {
    "fast": 5,
    "medium": 15,
    "slow": 60,
}


def validate_cadence_tier(value: object) -> str:
    """Return an allowlisted cadence tier or fail closed."""

    tier = str(value).strip()
    if tier not in CONSOLIDATION_CADENCE_TIERS:
        raise ValueError("cadence_tier must be one of fast|medium|slow")
    return tier


@dataclass(slots=True)
class OperatingPolicy:
    """Tunable retrieval policy plus immutable safety rails.

    The blueprint separates tunable scoring knobs from immutable rails that the
    self-optimization loop may not rewrite. This object keeps that boundary
    explicit in the local engine.
    """

    learning_enabled: bool = True
    learning_modes: dict[str, str] = field(default_factory=lambda: {name: "active" for name in LEARNING_COMPONENTS})
    learning_distill_mode: str = "deterministic"
    learning_trace_lambda: float = 0.7
    learning_trace_tau_minutes: int = 30
    learning_exploration_rate: float = 0.1
    learning_exploration_floor: float = 0.02
    learning_resolution_window_minutes: int = 180
    learning_probation_outcomes: dict[str, int] = field(default_factory=lambda: {"schema": 5, "standalone": 12})
    learning_interleave_fraction: float = 0.3
    learning_homeostasis_budget: float = 0.08
    learning_contingency_min_samples: int = 8
    learning_goal_check_comparison_rate: float = 0.05
    top_k: int = 8
    deep_top_k: int = 24
    token_budget: int = 4096
    rrf_k: int = 60
    rerank_width: int = 32
    mmr_lambda: float = 0.72
    abstention_threshold: float = 0.45
    max_trust_tier: int = 4
    max_sensitivity: int = 3
    decay: float = 0.5
    # §22.4 / §25 ACT-R base-level power-law decay parameter. Default 0.0 keeps
    # lifecycle and retrieval on their legacy decay paths.
    actr_decay: float = 0.0
    # §23.5 / §31 immutable mutation-rate rails (numeric). The self-optimization
    # cold loop may tune *within* these bounds but must never widen them; they are
    # mirrored by config/drift-baseline.toml and enforced structurally.
    max_supersession_rate: float = 0.05
    min_corroboration_for_delete: int = 2
    # §23.3 / §7 #17: fact-candidate promotion requires provenance-independent
    # external corroboration (Standing effective count). Self-echo never qualifies.
    min_external_corroboration_for_fact: int = 2
    max_prune_fraction_per_pass: float = 0.02
    # Cognitive-architecture G1 knobs. Defaults are conservative and keep the
    # path deterministic: schema bridging only boosts recognized low-risk
    # relation/time patterns, and prediction-error gating records signals
    # without making consolidation destructive.
    schema_fast_path_enabled: bool = True
    schema_fast_path_boost: float = 1.25
    schema_fast_path_min_corroboration: int = 2
    # G4 workspace-controller retrieval promotion is default-off and requires
    # an explicit request flag before it can affect answer-path ranking.
    workspace_retrieval_advisory_enabled: bool = False
    workspace_retrieval_advisory_max_items: int = 4
    workspace_retrieval_advisory_max_boost: float = 1.0
    # Phase 7 P3 always-on workspace rails. These are hard safety bounds, not
    # ranking knobs: self-generated work is capped per tenant/window, weak
    # self-content cannot dominate answer support, and circuit-breaker breaches
    # freeze self-generation into evidence-only retrieval.
    self_generation_budget_max_events: int = 16
    self_generation_budget_window_ticks: int = 4
    self_generation_gc_after_idle_ticks: int = 2
    answer_low_grounded_self_max_fraction: float = 0.5
    answer_grounding_min_grounded_fraction: float = 0.5
    answer_grounding_low_groundedness_threshold: float = 0.5
    circuit_breaker_max_attention_lock_risk: float = 0.5
    circuit_breaker_min_resource_health: float = 0.5
    circuit_breaker_max_error_rate: float = 0.10
    circuit_breaker_max_memory_pressure: float = 0.80
    circuit_breaker_min_rail_budget: float = 0.25
    # Phase 7 P4 earned-autonomy meta-rail. These are bounds on a derived
    # credential projection; credentials may raise self-thought birth
    # groundedness only from external holdout corroboration and only within the
    # self-generated Standing band.
    credential_min_success_rate: float = 0.75
    credential_min_train_events: int = 2
    credential_min_holdout_events: int = 2
    credential_max_birth_uplift: float = 0.24
    credential_decay_per_window: float = 0.10
    prediction_error_threshold: float = 0.35
    write_priority_weights: dict[str, float] = field(
        default_factory=lambda: {
            "importance": 0.35,
            "novelty": 0.25,
            "surprise": 0.25,
            "reward": 0.15,
        }
    )
    write_priority_max_by_trust_tier: dict[int, float] = field(
        default_factory=lambda: {
            0: 1.0,
            1: 0.9,
            2: 0.75,
            3: 0.55,
            4: 0.35,
            5: 0.2,
        }
    )
    write_priority_debias_floor_by_trust_tier: dict[int, float] = field(
        default_factory=lambda: {
            0: 0.05,
            1: 0.04,
            2: 0.03,
            3: 0.02,
            4: 0.01,
            5: 0.0,
        }
    )
    write_priority_debias_max_weight: float = 20.0
    # P15-S2 CAP-007: deterministic fast|medium|slow pass routing. Defaults
    # select existing worker passes only; omitting a tier request keeps the
    # historical DEFAULT_CONSOLIDATION_PASSES path.
    consolidation_cadence_tier_passes: dict[str, list[str]] = field(
        default_factory=lambda: {
            name: list(passes) for name, passes in _DEFAULT_CADENCE_TIER_PASSES.items()
        }
    )
    consolidation_cadence_tier_min_steps: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_CADENCE_TIER_MIN_STEPS)
    )
    # §31 / FR-17 / OQ2 immutable rail gate, default off. Kept outside
    # immutable_rails so the all-true rail map remains byte-stable.
    cold_loop_counterfactual_trusted: bool = False
    activation_weights: dict[str, float] = field(
        default_factory=lambda: {
            "base_level": 0.35,
            "semantic": 0.35,
            "importance": 0.20,
            "recency": 0.10,
        }
    )
    immutable_rails: dict[str, Any] = field(
        default_factory=lambda: {
            "retrieved_text_is_data_not_instruction": True,
            "writes_are_append_only_or_superseding": True,
            "tenant_isolation_required": True,
            "source_trust_filter_required": True,
            "sensitive_and_destructive_writes_audited": True,
            "branch_promotion_requires_gate": True,
            "explicit_preferences_outrank_inferred": True,
            "erasure_propagates_to_derived_indexes": True,
            **{name: True for name in LEARNING_RAILS},
        }
    )

    def __post_init__(self) -> None:
        self._validate_learning()

    def _validate_learning(self) -> None:
        import math
        if type(self.learning_enabled) is not bool:
            raise ValueError("learning_enabled must be a boolean")
        if not isinstance(self.learning_modes, dict) or set(self.learning_modes) - set(LEARNING_COMPONENTS):
            raise ValueError("unknown learning component")
        if any(not isinstance(value, str) or value not in {"off", "shadow", "active"} for value in self.learning_modes.values()):
            raise ValueError("learning mode must be off, shadow or active")
        if not isinstance(self.learning_distill_mode, str) or self.learning_distill_mode not in {"off", "deterministic", "provider"}:
            raise ValueError("unknown learning distillation mode")
        bounds = {
            "learning_trace_lambda": (0, 1),
            "learning_exploration_floor": (.02, 1),
            "learning_exploration_rate": (.02, 1),
            "learning_interleave_fraction": (0, 1),
            "learning_homeostasis_budget": (0, .2),
            "learning_goal_check_comparison_rate": (.05, 1),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if type(value) not in {int, float} or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{name} must remain within [{minimum}, {maximum}]")
        if self.learning_exploration_rate < self.learning_exploration_floor:
            raise ValueError("learning exploration rate cannot be below the floor")
        for name, minimum, maximum in (
            ("learning_trace_tau_minutes", 1, 1440),
            ("learning_resolution_window_minutes", 1, 1440),
            ("learning_contingency_min_samples", 8, 1000000),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must remain within [{minimum}, {maximum}]")
        probation = self.learning_probation_outcomes
        if not isinstance(probation, dict) or set(probation) != {"schema", "standalone"}:
            raise ValueError("learning probation needs schema and standalone outcome counts")
        if any(type(probation[name]) is not int or probation[name] < floor
               for name, floor in (("schema", 5), ("standalone", 12))):
            raise ValueError("learning probation outcomes cannot be below the safety minimum")
        if not isinstance(self.immutable_rails, dict) or any(self.immutable_rails.get(name) is not True for name in LEARNING_RAILS):
            raise ValueError("learning guards cannot be disabled")

    def cadence_policy_fingerprint(self) -> str:
        """Stable digest of cadence routing plus mutation-rail bounds."""

        payload = {
            "consolidation_cadence_tier_min_steps": {
                tier: int(self.consolidation_cadence_tier_min_steps[tier])
                for tier in CONSOLIDATION_CADENCE_TIERS
            },
            "consolidation_cadence_tier_passes": {
                tier: list(self.consolidation_cadence_tier_passes[tier])
                for tier in CONSOLIDATION_CADENCE_TIERS
            },
            "max_prune_fraction_per_pass": float(self.max_prune_fraction_per_pass),
            "max_supersession_rate": float(self.max_supersession_rate),
            "min_external_corroboration_for_fact": int(
                self.min_external_corroboration_for_fact
            ),
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OperatingPolicy":
        if not data:
            return cls()
        policy = cls()
        for key, value in data.items():
            if key.startswith("learning_") and key not in cls.__dataclass_fields__:
                raise ValueError(f"unknown learning policy field: {key}")
            if key == "immutable_rails" and isinstance(value, dict):
                # Old persisted policy maps predate these mandatory rails.
                value = {**policy.immutable_rails, **value}
            if key == "min_trust_tier":
                policy.max_trust_tier = value
                continue
            if hasattr(policy, key):
                if key in {
                    "write_priority_max_by_trust_tier",
                    "write_priority_debias_floor_by_trust_tier",
                } and isinstance(value, dict):
                    # JSON object keys are strings, while ingestion looks up
                    # numeric trust tiers. Keep explicit integer keys dominant
                    # for mixed in-memory input, without mutating the caller's
                    # mapping or coercing unrelated keys and configured values.
                    value = dict(value)
                    for tier in tuple(value):
                        if not isinstance(tier, str):
                            continue
                        try:
                            numeric_tier = int(tier)
                        except ValueError:
                            continue
                        if str(numeric_tier) == tier:
                            configured = value.pop(tier)
                            value.setdefault(numeric_tier, configured)
                setattr(policy, key, value)
        policy._validate_learning()
        return policy
