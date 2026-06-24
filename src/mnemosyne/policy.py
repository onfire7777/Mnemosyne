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
