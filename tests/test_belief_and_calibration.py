from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.belief import BeliefRevisionCore
from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence


TENANT = "tenant-c"
USER = "user-c"


def assertion(subject: str, predicate: str, object_value: str, confidence: float = 0.8) -> Assertion:
    return Assertion(
        tenant_id=TENANT,
        user_id=USER,
        subject=subject,
        predicate=predicate,
        object=object_value,
        confidence=confidence,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        status="active",
        trust_tier=3,
        access_policy={"tenant": TENANT},
    )


def test_belief_revision_classifies_add_update_noop_and_supersede() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    first = assertion("memory compiler", "storage", "Postgres", confidence=0.7)

    add = core.revise(first, rule="initial source")
    update = core.revise(assertion("memory compiler", "storage", "Postgres", confidence=0.9), rule="stronger source")
    noop = core.revise(assertion("memory compiler", "storage", "Postgres", confidence=0.5), rule="weaker duplicate")
    newer = assertion("memory compiler", "storage", "Postgres plus object storage", confidence=0.95)
    newer.valid_from = datetime(2026, 2, 1, tzinfo=UTC)
    supersede = core.revise(newer, rule="newer architecture")

    assert add.operation == "ADD"
    assert update.operation == "UPDATE"
    assert noop.operation == "NOOP"
    assert supersede.operation == "SUPERSEDE"
    assert add.justification_id in engine.justifications
    assert supersede.contradictions


def test_cascade_invalidation_retracts_dependent_beliefs() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    source_report = core.revise(assertion("primary source", "says", "A"))
    derived = assertion("derived conclusion", "is", "A-dependent")
    derived_report = core.add_derived_belief(derived, dependency_ids=[source_report.assertion_id], rule="if source then conclusion")

    invalidated = core.cascade_invalidate(TENANT, source_report.assertion_id, reason="source retracted")
    exported = engine.export_tenant(TENANT)
    statuses = {item["id"]: item["status"] for item in exported["assertions"]}

    assert source_report.assertion_id in invalidated
    assert derived_report.assertion_id in invalidated
    assert statuses[source_report.assertion_id] == "retracted"
    assert statuses[derived_report.assertion_id] == "retracted"


def test_contested_hypotheses_surface_alternatives_with_probabilities() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    first = assertion("release date", "is", "June", confidence=0.55)
    second = assertion("release date", "is", "July", confidence=0.45)
    second.valid_from = first.valid_from

    core.revise(first)
    contest = core.revise(second)
    hypotheses = core.contested_hypotheses(TENANT, "release date", "is")

    assert contest.operation == "CONTEST"
    assert {item["object"] for item in hypotheses} == {"June", "July"}
    assert round(sum(float(item["probability"]) for item in hypotheses), 6) == 1.0


def test_conformal_calibration_threshold_and_abstention() -> None:
    calibration = CalibrationSet(
        tenant_id=TENANT,
        memory_type="assertion",
        scores=[0.05, 0.12, 0.18, 0.23, 0.4, 0.6, 0.8],
        target_coverage=0.8,
    )

    threshold = conformal_threshold(calibration)

    assert 0.0 <= threshold <= 1.0
    assert should_abstain(threshold - 0.01, calibration) is True
    assert should_abstain(threshold + 0.2, calibration) is False
    assert should_abstain(0.99, calibration, prediction_set_size=0) is True


def test_justifications_are_exported_with_evidence_links() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="test",
            content="Evidence for a justified assertion.",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )
    claim = assertion("justified claim", "has", "evidence")
    claim.source_evidence_cids = [cid]

    report = core.revise(claim, rule="direct evidence")
    exported = engine.export_tenant(TENANT)
    justifications = {item["id"]: item for item in exported["justifications"]}

    assert report.justification_id in justifications
    assert justifications[report.justification_id]["evidence_cids"] == [cid]

