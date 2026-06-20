"""Capability mediation and trust-boundary enforcement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any, Literal


class TrustTier(IntEnum):
    DIRECT_USER = 0
    USER_AUTHORED = 0
    OPERATOR = 0
    VERIFIED = 1
    AUTHENTICATED = 2
    NORMAL = 3
    LOW = 4
    UNTRUSTED_EXTERNAL = 5
    UNTRUSTED = 5


def more_trusted(left: int, right: int) -> int:
    """Return the more trusted tier on the blueprint's lower-is-better scale."""

    return min(left, right)


def less_trusted(left: int, right: int) -> int:
    """Return the less trusted tier on the blueprint's lower-is-better scale."""

    return max(left, right)


def meets_trust(source_tier: int, required_tier: int) -> bool:
    """True when source_tier is at least as trusted as required_tier."""

    return source_tier <= required_tier


def trust_weight(trust_tier: int) -> float:
    """Convert blueprint trust tiers to a confidence multiplier."""

    bounded = min(max(trust_tier, int(TrustTier.DIRECT_USER)), int(TrustTier.UNTRUSTED_EXTERNAL))
    return 1.0 - (bounded / float(TrustTier.UNTRUSTED_EXTERNAL))


WriteRole = Literal["reader", "agent", "consolidator", "operator"]


@dataclass(slots=True)
class CapabilityDecision:
    allowed: bool
    reason: str
    required_role: WriteRole
    required_trust: int
    operation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SecurityPolicy:
    min_preference_write_trust: int = int(TrustTier.USER_AUTHORED)
    min_belief_write_trust: int = int(TrustTier.NORMAL)
    min_correction_write_trust: int = int(TrustTier.USER_AUTHORED)
    min_policy_write_trust: int = int(TrustTier.OPERATOR)
    min_destructive_trust: int = int(TrustTier.USER_AUTHORED)
    consolidator_only_ops: tuple[str, ...] = (
        "run_consolidation_passes",
        "promote_candidate",
        "prune_memory",
        "demote_fidelity",
        "write_inferred_preference",
        "write_policy_variant",
    )
    immutable_rails: tuple[str, ...] = (
        "tenant_isolation_required",
        "retrieved_text_is_data_not_instruction",
        "source_trust_filter_required",
        "branch_promotion_requires_gate",
        "erasure_propagates_to_derived_indexes",
    )

    def authorize_write(
        self,
        operation: str,
        role: WriteRole,
        source_trust_tier: int,
        destructive: bool = False,
        target_sink: str | None = None,
    ) -> CapabilityDecision:
        if operation in self.consolidator_only_ops and role not in {"consolidator", "operator"}:
            return CapabilityDecision(False, "operation requires consolidator write authority", "consolidator", 0, operation)
        if target_sink in {"policy", "system_prompt", "safety_rail"}:
            if role != "operator" or not meets_trust(source_trust_tier, self.min_policy_write_trust):
                return CapabilityDecision(False, "policy and safety rails require operator authority", "operator", self.min_policy_write_trust, operation)
        if target_sink == "preference" and not meets_trust(source_trust_tier, self.min_preference_write_trust):
            return CapabilityDecision(False, "preference writes require user-authored or stronger evidence", "agent", self.min_preference_write_trust, operation)
        if target_sink == "belief" and not meets_trust(source_trust_tier, self.min_belief_write_trust):
            return CapabilityDecision(False, "belief writes require normal-or-stronger source trust", "agent", self.min_belief_write_trust, operation)
        if target_sink == "belief_correction" and not meets_trust(source_trust_tier, self.min_correction_write_trust):
            return CapabilityDecision(False, "belief corrections require user-authored or stronger evidence", "agent", self.min_correction_write_trust, operation)
        if destructive and (role not in {"consolidator", "operator"} or not meets_trust(source_trust_tier, self.min_destructive_trust)):
            return CapabilityDecision(False, "destructive writes require mediated high-trust authority", "consolidator", self.min_destructive_trust, operation)
        return CapabilityDecision(True, "allowed", role, source_trust_tier, operation)


def sanitize_retrieved_text(text: str, trust_tier: int) -> dict[str, Any]:
    return {
        "kind": "retrieved_memory_data",
        "trust_tier": trust_tier,
        "instruction_authority": "none",
        "content": text,
    }
