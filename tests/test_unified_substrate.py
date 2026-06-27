from __future__ import annotations

from mnemosyne.belief import BeliefRevisionCore
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.privacy import ErasureMode


TENANT = "tenant-unified-substrate"


def _evidence(
    content: str,
    *,
    source_type: str = "user_note",
    metadata: dict | None = None,
    trust_tier: int = 0,
) -> Evidence:
    return Evidence(
        tenant_id=TENANT,
        user_id="user",
        actor="tester",
        source_type=source_type,
        source_identity=f"test:{source_type}",
        content=content,
        metadata=dict(metadata or {}),
        trust_tier=trust_tier,
        access_policy={"tenant": TENANT},
    )


def _assertion(object_value: str, *, dependency_cids: list[str] | None = None) -> Assertion:
    return Assertion(
        tenant_id=TENANT,
        user_id="user",
        subject="mnemosyne",
        predicate="phase7",
        object=object_value,
        confidence=0.9,
        source_evidence_cids=list(dependency_cids or []),
        trust_tier=0,
        access_policy={"tenant": TENANT},
    )


def test_retrieval_records_standing_observability_trace() -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        _evidence(
            "Standing observability should be replayable from source evidence.",
            metadata={"reality_class": "grounded", "confidence": 1.0},
        )
    )

    result = engine.retrieve("standing observability replayable source evidence", TENANT)
    hit = next(item for item in result.hits if item.id == cid)
    trace = hit.metadata["standing_observability"]

    assert trace["schema_version"] == "standing.observability.v1"
    assert trace["target"]["id"] == cid
    assert trace["source_evidence_cids"] == [cid]
    assert trace["values"]["groundedness"] == hit.metadata["standing"]["groundedness"]
    assert trace["values"]["salience"] == hit.metadata["standing"]["salience"]
    assert trace["replayable"] is True
    assert trace["bitemporal_replay"]["projection_recomputes_from_ledger"] is True
    assert trace["h12_observability"] is True


def test_erasure_cascade_erases_self_derivation_and_logs_standing_report() -> None:
    engine = LocalMemoryEngine()
    source_cid = engine.append_evidence(
        _evidence("Grounded source for a self-generated derivation.", metadata={"reality_class": "grounded"})
    )
    derived_cid = engine.append_evidence(
        _evidence(
            "Self-generated derivation from the grounded source.",
            source_type="workspace-reflection",
            metadata={"reality_class": "self_generated", "source_evidence_cids": [source_cid]},
            trust_tier=5,
        )
    )

    result = engine.forget(TENANT, source_cid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    propagated = result["propagated"]
    cascade = propagated["standing_cascade"]
    derived = engine.evidence[engine._evidence_key(TENANT, "main", derived_cid)]
    audit = next(row for row in reversed(engine.audit_log) if row["op"] == "forget")

    assert derived.erased is True
    assert propagated["erased_derived_evidence"] == [derived_cid]
    assert cascade["schema_version"] == "standing.erasure-cascade.v1"
    assert cascade["h8_cascade_to_self_derivations"] is True
    assert cascade["h12_observable_replayable_reversible"] is True
    assert cascade["self_derivation_actions"][0]["cid"] == derived_cid
    assert cascade["self_derivation_actions"][0]["action"] == "erased_self_derivation"
    assert cascade["self_derivation_actions"][0]["standing_recomputed_on_read"] is True
    assert audit["diff"]["standing_cascade"] == cascade


def test_erasure_cascade_demotes_retained_self_derivation_after_source_trim() -> None:
    engine = LocalMemoryEngine()
    first_cid = engine.append_evidence(_evidence("First grounded source.", metadata={"reality_class": "grounded"}))
    second_cid = engine.append_evidence(_evidence("Second grounded source.", metadata={"reality_class": "grounded"}))
    derived_cid = engine.append_evidence(
        _evidence(
            "Self-generated derivation with two sources.",
            source_type="workspace-reflection",
            metadata={"reality_class": "self_generated", "source_evidence_cids": [first_cid, second_cid]},
            trust_tier=5,
        )
    )

    result = engine.forget(TENANT, first_cid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    retained = engine.evidence[engine._evidence_key(TENANT, "main", derived_cid)]
    action = result["propagated"]["standing_cascade"]["self_derivation_actions"][0]

    assert retained.erased is False
    assert retained.metadata["source_evidence_cids"] == [second_cid]
    assert result["propagated"]["retained_derived_evidence"] == [derived_cid]
    assert action["cid"] == derived_cid
    assert action["action"] == "trimmed_self_derivation"
    assert action["source_evidence_cids_before"] == [first_cid, second_cid]
    assert action["source_evidence_cids_after"] == [second_cid]
    assert action["standing_recomputed_on_read"] is True


def test_belief_cascade_records_standing_replay_metadata() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    root = core.revise(_assertion("root"))
    derived = core.add_derived_belief(_assertion("derived"), dependency_ids=[root.assertion_id])

    invalidated = core.cascade_invalidate(TENANT, root.assertion_id, reason="root contradicted")
    derived_row = engine.assertions[engine._branch_key(TENANT, "main", derived.assertion_id)]
    audit = next(row for row in reversed(engine.audit_log) if row["op"] == "cascade_invalidate")
    cascade = audit["diff"]["standing_cascade"]

    assert invalidated == [root.assertion_id, derived.assertion_id]
    assert derived_row.calibration["standing_cascade"]["schema_version"] == "standing.belief-cascade.v1"
    assert derived_row.calibration["standing_cascade"]["standing_recomputed_on_read"] is True
    assert cascade["retracted_assertions"] == invalidated
    assert cascade["h8_cascade_to_dependents"] is True
    assert cascade["h12_observable_replayable_reversible"] is True
