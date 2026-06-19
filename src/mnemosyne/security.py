"""Capability mediation and trust-boundary enforcement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any, Literal


class TrustTier(IntEnum):
    UNTRUSTED = 0
    LOW = 1
    NORMAL = 2
    USER_AUTHORED = 3
    VERIFIED = 4
    OPERATOR = 5


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
    min_policy_write_trust: int = int(TrustTier.OPERATOR)
    min_destructive_trust: int = int(TrustTier.USER_AUTHORED)
    consolidator_only_ops: tuple[str, ...] = (
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
            if role != "operator" or source_trust_tier < self.min_policy_write_trust:
                return CapabilityDecision(False, "policy and safety rails require operator authority", "operator", self.min_policy_write_trust, operation)
        if target_sink == "preference" and source_trust_tier < self.min_preference_write_trust:
            return CapabilityDecision(False, "preference writes require user-authored or stronger evidence", "agent", self.min_preference_write_trust, operation)
        if destructive and (role not in {"consolidator", "operator"} or source_trust_tier < self.min_destructive_trust):
            return CapabilityDecision(False, "destructive writes require mediated high-trust authority", "consolidator", self.min_destructive_trust, operation)
        return CapabilityDecision(True, "allowed", role, source_trust_tier, operation)


def sanitize_retrieved_text(text: str, trust_tier: int) -> dict[str, Any]:
    return {
        "kind": "retrieved_memory_data",
        "trust_tier": trust_tier,
        "instruction_authority": "none",
        "content": text,
    }

