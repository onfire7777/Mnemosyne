"""Shadow-first policy optimization inside immutable rails."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.ids import new_id
from mnemosyne.policy import OperatingPolicy


@dataclass(slots=True)
class PolicyVariant:
    id: str
    activation_weights: dict[str, float]
    abstention_threshold: float
    top_k: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SelfModelRecord:
    tenant_id: str
    metric: str
    policy_version: str
    value: float
    window_start: datetime
    window_end: datetime
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["window_start"] = self.window_start.astimezone(UTC).isoformat()
        data["window_end"] = self.window_end.astimezone(UTC).isoformat()
        return data


@dataclass(slots=True)
class TripwireResult:
    passed: bool
    reason: str
    diversity: float
    proxy_true_gap: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SelfModelStore:
    def __init__(self) -> None:
        self.records: dict[str, SelfModelRecord] = {}

    def add(self, record: SelfModelRecord) -> str:
        self.records[record.id] = record
        return record.id

    def latest(self, tenant_id: str, metric: str) -> SelfModelRecord | None:
        matches = [record for record in self.records.values() if record.tenant_id == tenant_id and record.metric == metric]
        if not matches:
            return None
        return max(matches, key=lambda item: item.window_end)


def within_invariant_rails(base: OperatingPolicy, variant: PolicyVariant) -> bool:
    if variant.top_k < 1 or variant.top_k > 64:
        return False
    if variant.abstention_threshold < 0.05 or variant.abstention_threshold > 0.95:
        return False
    total = sum(variant.activation_weights.values())
    if abs(total - 1.0) > 0.001:
        return False
    if set(variant.activation_weights) != set(base.activation_weights):
        return False
    return all(base.immutable_rails.values())


class ShadowPolicyOptimizer:
    def __init__(self, engine: LocalMemoryEngine, cases: list[RegressionCase], self_model: SelfModelStore | None = None):
        self.engine = engine
        self.cases = cases
        self.self_model = self_model or SelfModelStore()

    def evaluate_variant(self, tenant_id: str, variant: PolicyVariant) -> GateResult:
        candidate = Candidate(
            id=variant.id,
            kind="policy",
            signature="policy retrieval activation confidence",
            description=f"top_k={variant.top_k}; abstention={variant.abstention_threshold}",
            branch=f"canary-policy-{variant.id}",
            source_evidence_cids=[],
        )
        gate = PromotionGate(self.engine, self.cases)

        def apply(engine: LocalMemoryEngine, branch: str) -> None:
            if not within_invariant_rails(engine.policy, variant):
                raise ValueError("policy variant violates invariant rails")
            engine.policy.activation_weights = dict(variant.activation_weights)
            engine.policy.abstention_threshold = variant.abstention_threshold
            engine.policy.top_k = variant.top_k

        try:
            result = gate.evaluate(tenant_id, candidate, apply)
        finally:
            self.engine.policy = OperatingPolicy()
        return result

    def propose_variant(self, tenant_id: str, metric: str = "retrieval_quality") -> PolicyVariant:
        latest = self.self_model.latest(tenant_id, metric)
        base = self.engine.policy
        if latest and latest.value < 0.7:
            return PolicyVariant(
                id=f"variant-{metric}-recall",
                activation_weights={"base_level": 0.25, "semantic": 0.45, "importance": 0.20, "recency": 0.10},
                abstention_threshold=min(base.abstention_threshold + 0.05, 0.9),
                top_k=min(base.top_k + 4, 64),
            )
        return PolicyVariant(
            id=f"variant-{metric}-stable",
            activation_weights=dict(base.activation_weights),
            abstention_threshold=base.abstention_threshold,
            top_k=base.top_k,
        )


def tripwire_check(diversity: float, proxy_score: float, true_score: float, min_diversity: float = 0.2, max_proxy_gap: float = 0.15) -> TripwireResult:
    gap = abs(proxy_score - true_score)
    if diversity < min_diversity:
        return TripwireResult(False, "diversity below rail", diversity, gap)
    if gap > max_proxy_gap:
        return TripwireResult(False, "proxy score diverges from true score", diversity, gap)
    return TripwireResult(True, "tripwires clear", diversity, gap)
