"""Operating policy and invariant rails."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class OperatingPolicy:
    """Tunable retrieval policy plus immutable safety rails.

    The blueprint separates tunable scoring knobs from immutable rails that the
    self-optimization loop may not rewrite. This object keeps that boundary
    explicit in the local engine.
    """

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
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OperatingPolicy":
        if not data:
            return cls()
        policy = cls()
        for key, value in data.items():
            if key == "min_trust_tier":
                policy.max_trust_tier = value
                continue
            if hasattr(policy, key):
                setattr(policy, key, value)
        return policy
