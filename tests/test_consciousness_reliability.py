from __future__ import annotations

from mnemosyne.consciousness import (
    BoundedCognitiveCycle,
    InteroceptiveProtoSelf,
    MetacognitiveMonitor,
    RealityMonitor,
    workspace_bottleneck,
)


def test_reality_monitor_tags_grounded_generated_and_external_support() -> None:
    monitor = RealityMonitor()

    grounded = monitor.tag(
        source_type="operator-evidence",
        actor="user",
        trust_tier=0,
        metadata={"reality_class": "evidence-grounded"},
        provenance_count=2,
    )
    generated = monitor.tag(source_type="generated-summary", actor="assistant", trust_tier=1)
    external = monitor.tag(source_type="web-suggestion", actor="external", trust_tier=2)

    assert grounded.reality_class == "evidence_grounded"
    assert generated.reality_class == "self_generated"
    assert external.reality_class == "externally_suggested"
    assert grounded.confidence > 0.8
    assert generated.confidence >= 0.7
    assert external.confidence >= 0.7


def test_reality_monitor_rejects_forged_grounded_external_label() -> None:
    monitor = RealityMonitor()

    forged = monitor.tag(
        source_type="web-suggestion",
        actor="external",
        trust_tier=2,
        metadata={"reality_class": "evidence-grounded"},
        provenance_count=2,
    )

    assert forged.reality_class == "unknown"
    assert forged.signals["explicit_label"] is False
    assert forged.signals["explicit_label_conflict"] is True
    assert forged.confidence < 0.8


def test_interoceptive_proto_self_escalates_attention_lock_risk() -> None:
    proto = InteroceptiveProtoSelf()

    stable = proto.snapshot(
        resource_health=0.95,
        error_rate=0.01,
        latency_ms=100.0,
        memory_pressure=0.20,
        confidence=0.90,
        rail_budget=0.90,
        cycle_index=1,
        max_cycles=6,
    )
    strained = proto.snapshot(
        resource_health=0.30,
        error_rate=0.20,
        latency_ms=1500.0,
        memory_pressure=0.90,
        confidence=0.25,
        rail_budget=0.10,
        cycle_index=6,
        max_cycles=6,
    )

    assert stable.escalation_required is False
    assert strained.escalation_required is True
    assert "cycle_budget_near_exhausted" in strained.reasons
    assert strained.attention_lock_risk > stable.attention_lock_risk


def test_bounded_cognitive_cycle_escalates_impasse_and_max_cycles() -> None:
    cycle = BoundedCognitiveCycle(max_cycles=3, tick_ms=250)

    assert cycle.tick(coherent=True, progressed=False)["state"] == "continue"
    assert cycle.tick(coherent=True, progressed=False)["state"] == "escalate_impasse"
    assert cycle.tick(coherent=True, progressed=True)["state"] == "escalate_max_cycles"


def test_workspace_bottleneck_keeps_highest_priority_items() -> None:
    selected = workspace_bottleneck(
        [
            {"id": "low", "priority": 0.1},
            {"id": "high", "priority": 0.9},
            {"id": "mid", "priority": 0.5},
        ],
        limit=2,
    )

    assert [item["id"] for item in selected] == ["high", "mid"]


def test_metacognitive_monitor_scores_confidence_and_abstention_alignment() -> None:
    monitor = MetacognitiveMonitor()
    monitor.observe(
        confidence=0.95,
        outcome_correct=True,
        abstained=False,
        answerable=True,
        reality_class="evidence_grounded",
        source="grounded-answer",
    )
    monitor.observe(
        confidence=0.82,
        outcome_correct=True,
        abstained=True,
        answerable=False,
        reality_class="externally_suggested",
        source="unsupported-suggestion",
    )
    monitor.observe(
        confidence=0.20,
        outcome_correct=False,
        abstained=False,
        answerable=True,
        reality_class="self_generated",
        source="unsupported-claim",
    )

    score = monitor.score()

    assert score.discrimination_auc == 1.0
    assert score.meta_d_prime == 1.0
    assert score.abstention_alignment == 1.0
    assert score.m_ratio == 1.0
    assert score.task_accuracy == 0.666667
    assert score.rows[0]["source"] == "grounded-answer"


def test_metacognitive_monitor_penalizes_inverted_confidence_and_bad_abstention() -> None:
    monitor = MetacognitiveMonitor()
    monitor.observe(confidence=0.20, outcome_correct=True, abstained=True, answerable=True)
    monitor.observe(confidence=0.90, outcome_correct=False, abstained=False, answerable=False)

    score = monitor.score()

    assert score.discrimination_auc == 0.0
    assert score.meta_d_prime == 0.0
    assert score.abstention_alignment == 0.0
    assert score.m_ratio == 0.0
