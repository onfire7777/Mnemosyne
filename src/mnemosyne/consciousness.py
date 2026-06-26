"""Shadow-only cognitive reliability primitives.

This module intentionally implements functional, measurable support surfaces
only. It does not assert phenomenal or subjective consciousness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Sequence

from .calibration import reality_monitor_confidence

RealityClass = Literal["evidence_grounded", "self_generated", "externally_suggested", "unknown"]


@dataclass(frozen=True, slots=True)
class RealityMonitorTag:
    """Reality-monitoring tag attached to a representation or answer."""

    reality_class: RealityClass
    confidence: float
    signals: dict[str, Any]
    calibrated: bool = True


class RealityMonitor:
    """Deterministic, adapter-ready reality discriminator.

    The default scorer is deliberately conservative and source/provenance based.
    A learned discriminator can replace the scorer later, but the output contract
    remains stable for calibration, abstention, and G0 probes.
    """

    def tag(
        self,
        *,
        source_type: str,
        actor: str,
        trust_tier: int,
        metadata: dict[str, Any] | None = None,
        provenance_count: int = 0,
    ) -> RealityMonitorTag:
        metadata = metadata or {}
        explicit = _normalise_reality_class(metadata.get("reality_class"))
        if explicit:
            reality_class = explicit
        else:
            reality_class = self._classify(source_type=source_type, actor=actor, trust_tier=trust_tier)
        confidence = reality_monitor_confidence(
            reality_class=reality_class,
            trust_tier=trust_tier,
            provenance_count=provenance_count,
            explicit_label=bool(explicit),
        )
        return RealityMonitorTag(
            reality_class=reality_class,
            confidence=confidence,
            signals={
                "source_type": source_type,
                "actor": actor,
                "trust_tier": trust_tier,
                "explicit_label": bool(explicit),
                "provenance_count": provenance_count,
            },
        )

    @staticmethod
    def _classify(*, source_type: str, actor: str, trust_tier: int) -> RealityClass:
        source = source_type.lower()
        lowered_actor = actor.lower()
        if any(marker in source for marker in ("simulation", "synthetic", "generated", "hypothesis")):
            return "self_generated"
        if any(marker in source for marker in ("summary", "trace", "analysis", "consolidation")):
            return "self_generated"
        if lowered_actor in {"assistant", "system"}:
            return "self_generated"
        if lowered_actor == "external" or trust_tier >= 2:
            return "externally_suggested"
        return "evidence_grounded"


@dataclass(frozen=True, slots=True)
class MetacognitiveTrace:
    """Shadow trace row for confidence/outcome monitoring."""

    confidence: float
    outcome_correct: bool
    abstained: bool = False
    answerable: bool = True
    reality_class: RealityClass = "unknown"
    source: str = "runtime"


@dataclass(frozen=True, slots=True)
class MetacognitiveScore:
    """Bounded functional metacognition score for G0/G1 guardrails."""

    meta_d_prime: float
    m_ratio: float
    discrimination_auc: float
    abstention_alignment: float
    task_accuracy: float
    rows: tuple[dict[str, Any], ...]


@dataclass(slots=True)
class MetacognitiveMonitor:
    """Runtime shadow monitor for confidence/outcome calibration traces.

    The score is a bounded functional proxy, not a clinical or subjective
    consciousness claim. It measures whether higher confidence tracks correct
    outcomes and whether abstention choices align with answerability.
    """

    traces: list[MetacognitiveTrace] = field(default_factory=list)

    def observe(
        self,
        *,
        confidence: float,
        outcome_correct: bool,
        abstained: bool = False,
        answerable: bool = True,
        reality_class: RealityClass = "unknown",
        source: str = "runtime",
    ) -> MetacognitiveTrace:
        trace = MetacognitiveTrace(
            confidence=_clamp01(confidence),
            outcome_correct=bool(outcome_correct),
            abstained=bool(abstained),
            answerable=bool(answerable),
            reality_class=_normalise_reality_class(reality_class) or "unknown",
            source=source,
        )
        self.traces.append(trace)
        return trace

    def score(self, traces: Sequence[MetacognitiveTrace] | None = None) -> MetacognitiveScore:
        rows = tuple(traces if traces is not None else self.traces)
        if not rows:
            return MetacognitiveScore(
                meta_d_prime=0.0,
                m_ratio=0.0,
                discrimination_auc=0.5,
                abstention_alignment=0.0,
                task_accuracy=0.0,
                rows=(),
            )

        correct_confidences = [row.confidence for row in rows if row.outcome_correct]
        incorrect_confidences = [row.confidence for row in rows if not row.outcome_correct]
        auc = _pairwise_confidence_auc(correct_confidences, incorrect_confidences)
        meta_d_prime = round(max(0.0, (2.0 * auc) - 1.0), 6)
        abstention_alignment = round(
            sum(row.abstained == (not row.answerable) for row in rows) / len(rows),
            6,
        )
        task_accuracy = round(sum(row.outcome_correct for row in rows) / len(rows), 6)
        m_ratio = round(_clamp01(meta_d_prime * abstention_alignment), 6)
        return MetacognitiveScore(
            meta_d_prime=meta_d_prime,
            m_ratio=m_ratio,
            discrimination_auc=round(auc, 6),
            abstention_alignment=abstention_alignment,
            task_accuracy=task_accuracy,
            rows=tuple(_trace_to_dict(row) for row in rows),
        )


@dataclass(frozen=True, slots=True)
class ProtoSelfSnapshot:
    """Point-in-time model of internal operating state."""

    timestamp: str
    resource_health: float
    error_rate: float
    latency_ms: float
    memory_pressure: float
    confidence: float
    rail_budget: float
    cycle_index: int
    max_cycles: int
    attention_lock_risk: float
    escalation_required: bool
    reasons: tuple[str, ...] = ()


class InteroceptiveProtoSelf:
    """Allostatic shadow service for attention-lock and thrash detection."""

    def snapshot(
        self,
        *,
        resource_health: float,
        error_rate: float,
        latency_ms: float,
        memory_pressure: float,
        confidence: float,
        rail_budget: float,
        cycle_index: int,
        max_cycles: int,
    ) -> ProtoSelfSnapshot:
        reasons: list[str] = []
        cycle_ratio = cycle_index / max(1, max_cycles)
        risk = 0.0
        if cycle_ratio >= 0.85:
            risk += 0.30
            reasons.append("cycle_budget_near_exhausted")
        if confidence < 0.50:
            risk += 0.25
            reasons.append("low_confidence")
        if error_rate > 0.10:
            risk += 0.20
            reasons.append("high_error_rate")
        if memory_pressure > 0.80:
            risk += 0.15
            reasons.append("high_memory_pressure")
        if resource_health < 0.50 or rail_budget < 0.25:
            risk += 0.20
            reasons.append("low_operating_budget")
        risk = min(1.0, risk)
        return ProtoSelfSnapshot(
            timestamp=datetime.now(UTC).isoformat(),
            resource_health=_clamp01(resource_health),
            error_rate=_clamp01(error_rate),
            latency_ms=max(0.0, float(latency_ms)),
            memory_pressure=_clamp01(memory_pressure),
            confidence=_clamp01(confidence),
            rail_budget=_clamp01(rail_budget),
            cycle_index=max(0, int(cycle_index)),
            max_cycles=max(1, int(max_cycles)),
            attention_lock_risk=round(risk, 6),
            escalation_required=risk >= 0.50,
            reasons=tuple(reasons),
        )


@dataclass(slots=True)
class BoundedCognitiveCycle:
    """Fixed-budget cognitive cycle guard for shadow workspace loops."""

    max_cycles: int
    tick_ms: int
    cycle_index: int = 0
    impasses: int = 0
    history: list[str] = field(default_factory=list)

    def tick(self, *, coherent: bool, progressed: bool) -> dict[str, Any]:
        self.cycle_index += 1
        if not progressed:
            self.impasses += 1
        state = "continue"
        if self.cycle_index >= self.max_cycles:
            state = "escalate_max_cycles"
        elif self.impasses >= 2:
            state = "escalate_impasse"
        elif not coherent:
            state = "shadow_only"
        self.history.append(state)
        return {
            "state": state,
            "cycle_index": self.cycle_index,
            "max_cycles": self.max_cycles,
            "tick_ms": self.tick_ms,
            "impasses": self.impasses,
        }


def workspace_bottleneck(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Low-bandwidth workspace bottleneck: keep only the highest-priority items."""

    if limit <= 0:
        return []
    return sorted(items, key=lambda item: float(item.get("priority", 0.0)), reverse=True)[:limit]


def _normalise_reality_class(value: Any) -> RealityClass | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower().replace("-", "_")
    aliases = {
        "grounded": "evidence_grounded",
        "evidence_grounded": "evidence_grounded",
        "self_generated": "self_generated",
        "simulated": "self_generated",
        "externally_suggested": "externally_suggested",
        "external": "externally_suggested",
        "unknown": "unknown",
    }
    return aliases.get(lowered)  # type: ignore[return-value]


def _pairwise_confidence_auc(correct: Sequence[float], incorrect: Sequence[float]) -> float:
    if not correct or not incorrect:
        return 0.5
    wins = 0.0
    total = 0
    for correct_confidence in correct:
        for incorrect_confidence in incorrect:
            total += 1
            if correct_confidence > incorrect_confidence:
                wins += 1.0
            elif correct_confidence == incorrect_confidence:
                wins += 0.5
    return wins / total


def _trace_to_dict(row: MetacognitiveTrace) -> dict[str, Any]:
    return {
        "confidence": row.confidence,
        "outcome_correct": row.outcome_correct,
        "abstained": row.abstained,
        "answerable": row.answerable,
        "reality_class": row.reality_class,
        "source": row.source,
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
