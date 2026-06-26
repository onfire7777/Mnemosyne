from __future__ import annotations

from mnemosyne.consciousness import (
    BoundedCognitiveCycle,
    InteroceptiveProtoSelf,
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
