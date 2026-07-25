"""Lease #13 — AGM expansion/revision/contraction + ATMS labels (I2 / FR-10)."""

from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.belief import AGM_OPERATIONS, BeliefRevisionCore, agm_operation
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion

TENANT = "tenant-agm"
USER = "user-agm"


def _assertion(
    subject: str,
    predicate: str,
    object_value: str,
    *,
    confidence: float = 0.8,
    valid_from: datetime | None = None,
) -> Assertion:
    return Assertion(
        tenant_id=TENANT,
        user_id=USER,
        subject=subject,
        predicate=predicate,
        object=object_value,
        confidence=confidence,
        valid_from=valid_from or datetime(2026, 1, 1, tzinfo=UTC),
        status="active",
        trust_tier=3,
        access_policy={"tenant": TENANT},
    )


def test_agm_operations_map_includes_contraction() -> None:
    assert AGM_OPERATIONS["ADD"] == "expansion"
    assert AGM_OPERATIONS["SUPERSEDE"] == "revision"
    assert AGM_OPERATIONS["CONTRACTION"] == "contraction"
    assert agm_operation("CONTRACTION") == "contraction"
    assert agm_operation("NOOP") == "none"


def test_revise_surfaces_agm_operation_and_atms_labels() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    report = core.revise(_assertion("ship", "status", "docked"), rule="seed")
    assert report.operation == "ADD"
    assert report.agm_operation == "expansion"
    assert report.assertion_id in report.atms_by_assertion_id
    assert report.atms_by_assertion_id[report.assertion_id] == "in"


def test_expansion_keeps_belief_in() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    r = core.revise(_assertion("alpha", "is", "1", confidence=0.7))
    assert r.agm_operation == "expansion"
    assert core.atms_label(TENANT, r.assertion_id) == "in"
    statuses = {a.id: a.status for a in engine.assertions.values() if a.tenant_id == TENANT}
    assert statuses[r.assertion_id] == "active"


def test_revision_minimal_change_supersede() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    first = core.revise(_assertion("project", "status", "draft", confidence=0.6))
    assert first.agm_operation == "expansion"
    newer = _assertion("project", "status", "shipped", confidence=0.95)
    newer.valid_from = datetime(2026, 3, 1, tzinfo=UTC)
    second = core.revise(newer, rule="newer fact")
    assert second.operation == "SUPERSEDE"
    assert second.agm_operation == "revision"
    assert second.atms_by_assertion_id[second.assertion_id] == "in"
    # Prior peer remains in store; new belief is in
    assert core.atms_label(TENANT, second.assertion_id) == "in"


def test_contraction_retracts_root_and_cascade_dependents() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    source = core.revise(_assertion("primary", "says", "A"))
    derived = _assertion("derived", "is", "A-dependent")
    dep = core.add_derived_belief(
        derived,
        dependency_ids=[source.assertion_id],
        rule="if source then conclusion",
    )
    report = core.contract(TENANT, source.assertion_id, reason="operator contraction")
    assert report.operation == "CONTRACTION"
    assert report.agm_operation == "contraction"
    assert source.assertion_id in report.affected_assertion_ids
    assert dep.assertion_id in report.affected_assertion_ids
    # ATMS: both out after contraction cascade
    assert report.atms_by_assertion_id[source.assertion_id] == "out"
    assert report.atms_by_assertion_id[dep.assertion_id] == "out"
    assert core.atms_label(TENANT, source.assertion_id) == "out"
    assert core.atms_label(TENANT, dep.assertion_id) == "out"
    exported = engine.export_tenant(TENANT)
    statuses = {item["id"]: item["status"] for item in exported["assertions"]}
    assert statuses[source.assertion_id] == "retracted"
    assert statuses[dep.assertion_id] == "retracted"


def test_contraction_scopes_cascade_to_requested_branch() -> None:
    """contract(branch=X) must not retract assertions on another branch."""
    engine = LocalMemoryEngine()
    engine.branch("experiment", frm="main", kind="scratch")
    core = BeliefRevisionCore(engine)
    main_report = core.revise(_assertion("topic", "is", "main-value"), branch="main")
    other = _assertion("topic", "is", "other-value")
    other.branch = "experiment"
    other_report = core.revise(other, branch="experiment")
    report = core.contract(
        TENANT, other_report.assertion_id, reason="drop experiment", branch="experiment"
    )
    assert report.agm_operation == "contraction"
    assert core.atms_label(TENANT, other_report.assertion_id, branch="experiment") == "out"
    assert core.atms_label(TENANT, main_report.assertion_id, branch="main") == "in"
    statuses = {
        (a.id, a.branch): a.status
        for a in engine.assertions.values()
        if a.tenant_id == TENANT
    }
    assert statuses[(main_report.assertion_id, "main")] == "active"
    assert statuses[(other_report.assertion_id, "experiment")] == "retracted"


def test_contraction_isolates_engine_branch_clones_same_id() -> None:
    """engine.branch() clones assertions with the same id — cascade must not collapse them."""
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    seed = core.revise(_assertion("clone-topic", "is", "shared"))
    engine.branch("scratch", frm="main", kind="scratch")
    # Same assertion id now exists on main and scratch
    clones = [
        a for a in engine.assertions.values() if a.tenant_id == TENANT and a.id == seed.assertion_id
    ]
    assert {a.branch for a in clones} == {"main", "scratch"}
    report = core.contract(TENANT, seed.assertion_id, reason="contract main only", branch="main")
    assert report.agm_operation == "contraction"
    statuses = {
        (a.id, a.branch): a.status
        for a in engine.assertions.values()
        if a.tenant_id == TENANT and a.id == seed.assertion_id
    }
    assert statuses[(seed.assertion_id, "main")] == "retracted"
    assert statuses[(seed.assertion_id, "scratch")] == "active"
    assert core.atms_label(TENANT, seed.assertion_id, branch="main") == "out"
    assert core.atms_label(TENANT, seed.assertion_id, branch="scratch") == "in"


def test_contraction_retains_unrelated_belief_consistency() -> None:
    """Contracting one belief must not retract an independent expansion."""
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    keep = core.revise(_assertion("unrelated", "fact", "stable"))
    drop = core.revise(_assertion("ephemeral", "fact", "gone"))
    report = core.contract(TENANT, drop.assertion_id, reason="drop ephemeral")
    assert report.agm_operation == "contraction"
    assert core.atms_label(TENANT, keep.assertion_id) == "in"
    assert core.atms_label(TENANT, drop.assertion_id) == "out"
    statuses = {
        a.id: a.status
        for a in engine.assertions.values()
        if a.tenant_id == TENANT
    }
    assert statuses[keep.assertion_id] == "active"
    assert statuses[drop.assertion_id] == "retracted"
