"""Blueprint-parity regression tests for the CC-BC lane.

Covers the belief / calibration / consolidation / graph / lifecycle modules
against the v2 blueprint's Phase 2/3 guarantees:

* FR-10 belief-revision core (TMS + AGM): classify/revise, multi-level cascade
  invalidation, branch isolation, and multi-hypothesis contested beliefs.
* I8 metacognitive confidence: conformal threshold + selective abstention and
  the calibration-tuning gate (coverage / false-accept bounds).
* §25 forgetting & lifecycle: graduated fidelity tiers, exponential salience
  decay, the fuzzy-trace confabulation guard, and spaced-repetition rehearsal.
* §22 graph channel: the local Personalized-PageRank adapter delegation seam
  and its benchmark harness.

These complement the cross-module coverage in ``test_blueprint_later_phases``
and the declarative coverage in ``test_belief_and_calibration`` by pinning the
helper surfaces those suites do not exercise directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.belief import (
    BeliefRevisionCore,
    agm_operation,
    belief_revision_fingerprint,
    validate_belief_revision_cases,
)
from mnemosyne.calibration import (
    CalibrationExample,
    CalibrationSet,
    conformal_prediction_set,
    conformal_should_abstain,
    conformal_threshold,
    nonconformity_score,
    should_abstain,
    tune_calibration_set,
)
from mnemosyne.consolidation import ConsolidationJob, ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.graph import LocalRelationGraphAdapter, benchmark_graph_adapter
from mnemosyne.lifecycle import (
    FidelityTier,
    LifecycleState,
    apply_rehearsal_schedule,
    decayed_salience,
    demotion_decision,
    forgetting_policy_fingerprint,
    lifecycle_state_from_dict,
    next_fidelity_tier,
    next_rehearsal_days,
    rehearsal_due,
    sole_support_requires_abstention,
    validate_forgetting_policy_cases,
)
from mnemosyne.models import Assertion, Evidence, Relation

TENANT = "tenant-bc"
USER = "user-bc"
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def mk_assertion(
    subject: str,
    predicate: str,
    object_value: str,
    *,
    confidence: float = 0.8,
    valid_from: datetime = BASE,
    cids: list[str] | None = None,
) -> Assertion:
    return Assertion(
        tenant_id=TENANT,
        user_id=USER,
        subject=subject,
        predicate=predicate,
        object=object_value,
        confidence=confidence,
        valid_from=valid_from,
        status="active",
        source_evidence_cids=list(cids or []),
        trust_tier=0,
        access_policy={"tenant": TENANT},
    )


# --------------------------------------------------------------------------- #
# Calibration (I8 — conformal confidence + abstention)
# --------------------------------------------------------------------------- #


def test_conformal_threshold_empty_calibration_abstains_everything() -> None:
    empty = CalibrationSet(tenant_id=TENANT, memory_type="assertion", scores=[], target_coverage=0.9)
    # With no calibration evidence the threshold is the maximum, so any
    # confidence below 1.0 abstains — fail-closed metacognition.
    assert conformal_threshold(empty) == 1.0
    assert should_abstain(0.99, empty) is True


def test_conformal_threshold_is_monotone_in_target_coverage() -> None:
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    lenient = CalibrationSet(TENANT, "assertion", list(scores), target_coverage=0.5)
    strict = CalibrationSet(TENANT, "assertion", list(scores), target_coverage=0.9)
    # Requiring higher coverage of correct memories lowers the accept threshold
    # (more correct answers must clear the bar), never raises it.
    assert conformal_threshold(strict) <= conformal_threshold(lenient)


def test_calibration_example_from_mapping_validates_and_clamps() -> None:
    high = CalibrationExample.from_mapping({"confidence": 1.5, "correct": True})
    low = CalibrationExample.from_mapping({"confidence": -0.4, "correct": False})
    assert high.confidence == 1.0
    assert low.confidence == 0.0
    with pytest.raises(ValueError):
        CalibrationExample.from_mapping({"correct": True})
    with pytest.raises(ValueError):
        CalibrationExample.from_mapping({"confidence": 0.5})
    with pytest.raises(ValueError):
        CalibrationExample.from_mapping({"confidence": 0.5, "correct": True, "prediction_set_size": -1})


def test_tune_calibration_set_accepts_well_separated_examples() -> None:
    examples = [CalibrationExample(0.9, True) for _ in range(18)]
    examples += [CalibrationExample(0.1, False) for _ in range(2)]
    result = tune_calibration_set(tenant_id=TENANT, memory_type="assertion", examples=examples)
    assert result.ok is True
    assert result.failures == []
    assert result.threshold == pytest.approx(0.9)
    assert result.metrics["false_accept_rate"] == 0.0
    assert result.metrics["correct_coverage"] == 1.0
    assert result.to_dict()["ok"] is True


def test_tune_calibration_set_fails_on_thin_evidence() -> None:
    result = tune_calibration_set(
        tenant_id=TENANT,
        memory_type="assertion",
        examples=[CalibrationExample(0.9, True), CalibrationExample(0.1, False)],
    )
    assert result.ok is False
    assert any("below required minimum" in failure for failure in result.failures)


def test_tune_calibration_set_fails_on_high_false_accept_rate() -> None:
    # Incorrect memories that masquerade with high confidence must trip the
    # false-accept guard even when the example count is sufficient.
    examples = [CalibrationExample(0.9, True) for _ in range(18)]
    examples += [CalibrationExample(0.95, False) for _ in range(10)]
    result = tune_calibration_set(tenant_id=TENANT, memory_type="assertion", examples=examples)
    assert result.ok is False
    assert any("false accept rate" in failure for failure in result.failures)


def test_conformal_prediction_set_tracks_nonconformity_and_threshold() -> None:
    calibration = CalibrationSet(TENANT, "assertion", [0.2, 0.3, 0.5, 0.7, 0.9], target_coverage=0.6)
    threshold = conformal_threshold(calibration)
    assert nonconformity_score(1.0) == 0.0
    assert nonconformity_score(0.0) == 1.0
    candidates = [
        ("low", threshold - 0.05),
        ("at", threshold),
        ("high", min(1.0, threshold + 0.2)),
    ]
    chosen = conformal_prediction_set(candidates, calibration)
    assert "low" not in chosen
    assert {"at", "high"} <= set(chosen)
    # Higher confidence ranks earlier in the prediction set.
    assert chosen.index("high") < chosen.index("at")


def test_conformal_should_abstain_on_empty_or_oversized_set() -> None:
    calibration = CalibrationSet(TENANT, "assertion", [0.5, 0.6, 0.7, 0.8, 0.9], target_coverage=0.8)
    threshold = conformal_threshold(calibration)
    # No candidate clears the bar -> empty set -> abstain.
    assert conformal_should_abstain([("a", 0.0), ("b", 0.01)], calibration) is True
    # Exactly one well-supported candidate -> answer.
    assert conformal_should_abstain([("a", min(1.0, threshold + 0.2)), ("b", 0.0)], calibration) is False
    # Too many equally-supported candidates -> too ambiguous -> abstain.
    oversized = [(f"c{index}", 1.0) for index in range(5)]
    assert conformal_should_abstain(oversized, calibration, max_set_size=3) is True


# --------------------------------------------------------------------------- #
# Belief revision (FR-10 — TMS + AGM)
# --------------------------------------------------------------------------- #


def test_cascade_invalidation_propagates_through_multiple_levels() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    root = core.revise(mk_assertion("root", "states", "A"))
    mid = core.add_derived_belief(
        mk_assertion("mid", "implies", "B"), dependency_ids=[root.assertion_id]
    )
    leaf = core.add_derived_belief(
        mk_assertion("leaf", "implies", "C"), dependency_ids=[mid.assertion_id]
    )

    invalidated = core.cascade_invalidate(TENANT, root.assertion_id, reason="root retracted")

    assert {root.assertion_id, mid.assertion_id, leaf.assertion_id} <= set(invalidated)
    statuses = {item["id"]: item["status"] for item in engine.export_tenant(TENANT)["assertions"]}
    assert statuses[leaf.assertion_id] == "retracted"


def test_classify_marks_update_when_new_evidence_arrives_at_equal_confidence() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    first = core.revise(mk_assertion("db", "is", "Postgres", confidence=0.8))
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="doc",
            content="Confirms Postgres again from a second source.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    second = core.revise(mk_assertion("db", "is", "Postgres", confidence=0.8, cids=[cid]))
    assert first.operation == "ADD"
    # Equal confidence but fresh corroborating evidence is an UPDATE, not a NOOP.
    assert second.operation == "UPDATE"


def test_revision_is_isolated_per_branch() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    core.revise(mk_assertion("server", "runs", "main-build"), branch="main")
    engine.branch("feature", tenant_id=TENANT)
    # A conflicting revision on the forked branch must stay on that branch and
    # never leak back into main's current truth.
    core.revise(mk_assertion("server", "runs", "feature-build"), branch="feature")
    main_hypotheses = core.contested_hypotheses(TENANT, "server", "runs", branch="main")
    feature_hypotheses = core.contested_hypotheses(TENANT, "server", "runs", branch="feature")
    assert {row["object"] for row in main_hypotheses} == {"main-build"}
    assert "feature-build" in {row["object"] for row in feature_hypotheses}


def test_contested_hypotheses_rank_and_normalise_three_alternatives() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    core.revise(mk_assertion("release", "is", "June", confidence=0.6))
    core.revise(mk_assertion("release", "is", "July", confidence=0.3))
    core.revise(mk_assertion("release", "is", "August", confidence=0.1))

    hypotheses = core.contested_hypotheses(TENANT, "release", "is")

    assert [row["object"] for row in hypotheses] == ["June", "July", "August"]
    assert round(sum(float(row["probability"]) for row in hypotheses), 6) == 1.0
    assert hypotheses[0]["probability"] > hypotheses[1]["probability"] > hypotheses[2]["probability"]


def test_validate_belief_revision_cases_passes_and_flags_missing_required() -> None:
    cases = [
        {
            "id": "supersede-db",
            "assertions": [
                {
                    "ref": "first",
                    "subject": "db",
                    "predicate": "is",
                    "object": "Postgres",
                    "confidence": 0.7,
                    "valid_from": "2026-01-01T00:00:00+00:00",
                },
                {
                    "ref": "second",
                    "subject": "db",
                    "predicate": "is",
                    "object": "MySQL",
                    "confidence": 0.9,
                    "valid_from": "2026-02-01T00:00:00+00:00",
                },
            ],
            "expected": {
                "operations": {"first": "ADD", "second": "SUPERSEDE"},
                "min_contradictions": 1,
            },
        }
    ]
    report = validate_belief_revision_cases(cases, min_cases=1)
    assert report["ok"] is True
    assert report["summary"]["passed"] == 1
    assert report["fingerprint"] == belief_revision_fingerprint(cases)

    missing = validate_belief_revision_cases(cases, required_case_ids=["not-present"])
    assert missing["ok"] is False
    assert any(item["code"] == "missing_required_case" for item in missing["findings"])


def test_agm_operation_maps_each_classification() -> None:
    assert agm_operation("ADD") == "expansion"
    assert agm_operation("UPDATE") == "expansion"
    assert agm_operation("SUPERSEDE") == "revision"
    assert agm_operation("CONTEST") == "expansion"
    assert agm_operation("NOOP") == "none"
    assert agm_operation("unrecognised") == "expansion"


def test_atms_label_tracks_support_and_retraction() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    root = core.revise(mk_assertion("root", "states", "A"))
    derived = core.add_derived_belief(
        mk_assertion("leaf", "implies", "B"), dependency_ids=[root.assertion_id]
    )
    assert core.atms_label(TENANT, root.assertion_id) == "in"
    assert core.atms_label(TENANT, derived.assertion_id) == "in"

    core.cascade_invalidate(TENANT, root.assertion_id)
    # Retracting the premise pulls both the premise and its derived belief out.
    assert core.atms_label(TENANT, root.assertion_id) == "out"
    assert core.atms_label(TENANT, derived.assertion_id) == "out"
    assert core.atms_label(TENANT, "missing-id") == "out"


def test_tier0_correction_supersedes_lower_trust_in_same_turn() -> None:
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    # A lower-trust machine-inferred memory is established first.
    machine = mk_assertion("preferred db", "is", "MySQL", confidence=0.6)
    machine.trust_tier = 3
    core.revise(machine)
    # A tier-0 user correction in the SAME turn (same valid_from) must override it
    # immediately, not merely contest it.
    correction = mk_assertion("preferred db", "is", "Postgres", confidence=0.9)
    report = core.apply_tier0_correction(correction)

    assert report.operation == "SUPERSEDE"
    statuses = {item["object"]: item["status"] for item in engine.export_tenant(TENANT)["assertions"]}
    assert statuses["MySQL"] == "superseded"
    assert statuses["Postgres"] == "active"
    # Current truth surfaces only the correction, not the superseded memory.
    assert {row["object"] for row in core.contested_hypotheses(TENANT, "preferred db", "is")} == {"Postgres"}


# --------------------------------------------------------------------------- #
# Lifecycle (§25 — graduated forgetting + rehearsal)
# --------------------------------------------------------------------------- #


def test_next_fidelity_tier_progresses_and_saturates() -> None:
    assert next_fidelity_tier(FidelityTier.VERBATIM) == FidelityTier.EXTRACTIVE_SUMMARY
    assert next_fidelity_tier(FidelityTier.EXTRACTIVE_SUMMARY) == FidelityTier.ABSTRACTIVE_GIST
    assert next_fidelity_tier(FidelityTier.ABSTRACTIVE_GIST) == FidelityTier.STATISTICAL_TRACE
    assert next_fidelity_tier(FidelityTier.STATISTICAL_TRACE) == FidelityTier.STATISTICAL_TRACE


def test_decayed_salience_rewards_recent_access() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    fresh = LifecycleState("fresh", FidelityTier.VERBATIM, 0.8, 0.5, 10, now)
    stale = LifecycleState("stale", FidelityTier.VERBATIM, 0.8, 0.5, 10, now - timedelta(days=180))
    assert decayed_salience(fresh, now) > decayed_salience(stale, now)


def test_protected_state_is_never_demoted() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    protected = LifecycleState(
        "protected",
        FidelityTier.VERBATIM,
        salience=0.01,
        importance=0.0,
        access_count=0,
        last_accessed=now - timedelta(days=300),
        protected=True,
    )
    state, demoted = demotion_decision(protected, now)
    assert demoted is False
    assert state is protected


def test_must_keep_memory_is_never_demoted_even_when_cold() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    # Low utility and stale, and not yet due for rehearsal: the must-keep flag
    # alone must still block demotion (I7).
    keep = LifecycleState(
        "keep-cold",
        FidelityTier.EXTRACTIVE_SUMMARY,
        salience=0.01,
        importance=0.0,
        access_count=0,
        last_accessed=now - timedelta(days=300),
        must_keep=True,
        next_rehearsal_at=now + timedelta(days=30),
    )
    state, demoted = demotion_decision(keep, now, utility_threshold=0.2)
    assert demoted is False
    assert state.tier == FidelityTier.EXTRACTIVE_SUMMARY


def test_verbatim_pointer_survives_demotion_and_round_trips() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    state = LifecycleState(
        "with-pointer",
        FidelityTier.EXTRACTIVE_SUMMARY,
        salience=0.02,
        importance=0.0,
        access_count=0,
        last_accessed=now - timedelta(days=200),
        verbatim_pointer="cid-verbatim-1",
    )
    demoted, changed = demotion_decision(state, now, utility_threshold=0.2)
    assert changed is True
    assert demoted.tier == FidelityTier.ABSTRACTIVE_GIST
    # I7/§25: the pointer to the verbatim original survives demotion so a gist
    # can always be reconstructed from raw evidence.
    assert demoted.verbatim_pointer == "cid-verbatim-1"
    assert demoted.to_dict()["verbatim_pointer"] == "cid-verbatim-1"
    restored = lifecycle_state_from_dict(demoted.to_dict())
    assert restored.verbatim_pointer == "cid-verbatim-1"


def test_sole_low_fidelity_support_requires_abstention() -> None:
    gist_risky = LifecycleState(
        "gist", FidelityTier.ABSTRACTIVE_GIST, 0.3, 0.2, 0, None, confabulation_risk=True
    )
    gist_clean = LifecycleState(
        "gist2", FidelityTier.ABSTRACTIVE_GIST, 0.3, 0.2, 0, None, confabulation_risk=False
    )
    verbatim = LifecycleState("verb", FidelityTier.VERBATIM, 0.9, 0.5, 0, None)
    assert sole_support_requires_abstention([gist_risky]) is True
    assert sole_support_requires_abstention([gist_clean]) is False
    assert sole_support_requires_abstention([verbatim]) is False
    assert sole_support_requires_abstention([gist_risky, verbatim]) is False
    assert sole_support_requires_abstention([]) is False


def test_rehearsal_schedule_advances_must_keep_memory() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    state = LifecycleState(
        "keep",
        FidelityTier.VERBATIM,
        salience=0.4,
        importance=0.5,
        access_count=2,
        last_accessed=now - timedelta(days=10),
        must_keep=True,
    )
    assert rehearsal_due(state, now) is True
    rehearsed, did_rehearse = apply_rehearsal_schedule(state, now)
    assert did_rehearse is True
    assert rehearsed.successful_rehearsals == 1
    assert rehearsed.last_rehearsed_at == now
    assert rehearsed.next_rehearsal_at == now + timedelta(days=next_rehearsal_days(1))
    assert rehearsed.salience >= state.salience


def test_rehearsal_skips_ordinary_memory() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    plain = LifecycleState("plain", FidelityTier.VERBATIM, 0.4, 0.5, 0, now, must_keep=False)
    assert rehearsal_due(plain, now) is False
    state, did_rehearse = apply_rehearsal_schedule(plain, now)
    assert did_rehearse is False
    assert state is plain


def test_validate_forgetting_policy_cases_passes_and_fails() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    stale_at = (now - timedelta(days=200)).isoformat()
    passing = [
        {
            "id": "demote-stale-summary",
            "state": {
                "item_id": "s1",
                "tier": "extractive_summary",
                "salience": 0.02,
                "importance": 0.0,
                "access_count": 0,
                "last_accessed": stale_at,
            },
            "expected": {"demoted": True, "tier": "abstractive_gist"},
        }
    ]
    report = validate_forgetting_policy_cases(passing, now=now, utility_threshold=0.2)
    assert report["ok"] is True
    assert report["fingerprint"] == forgetting_policy_fingerprint(passing, utility_threshold=0.2)

    failing = [
        {
            "id": "hot-memory-should-not-demote",
            "state": {
                "item_id": "s2",
                "tier": "verbatim",
                "salience": 0.9,
                "importance": 0.9,
                "access_count": 50,
                "last_accessed": now.isoformat(),
            },
            "expected": {"demoted": True},
        }
    ]
    report_fail = validate_forgetting_policy_cases(failing, now=now)
    assert report_fail["ok"] is False


# --------------------------------------------------------------------------- #
# Graph channel (§22 — PPR adapter seam)
# --------------------------------------------------------------------------- #


def test_local_graph_adapter_is_a_pure_delegation_seam() -> None:
    engine = LocalMemoryEngine()
    for source, target in (("A", "B"), ("B", "C"), ("C", "D")):
        engine.add_relation(
            Relation(
                tenant_id=TENANT,
                source=source,
                predicate="links",
                target=target,
                source_evidence_cids=[],
                access_policy={"tenant": TENANT},
            )
        )
    adapter = LocalRelationGraphAdapter(engine)
    assert adapter.name == "local-relation-ppr"
    direct = engine.graph_ppr(["A"], 5, tenant_id=TENANT)
    via_adapter = adapter.ppr(["A"], 5, tenant_id=TENANT)
    assert [hit.id for hit in via_adapter] == [hit.id for hit in direct]
    assert len(adapter.ppr(["A"], 1, tenant_id=TENANT)) <= 1


def test_graph_benchmark_handles_empty_query_set() -> None:
    adapter = LocalRelationGraphAdapter(LocalMemoryEngine())
    result = benchmark_graph_adapter(adapter, [], k=4)
    assert result.query_count == 0
    assert result.total_hits == 0
    assert result.p50_ms == 0.0
    assert result.p95_ms == 0.0
    assert result.max_ms == 0.0


# --------------------------------------------------------------------------- #
# Consolidation (FR-12 — gated warm-loop promotion)
# --------------------------------------------------------------------------- #


def test_consolidation_worker_blocks_promotion_on_unsatisfiable_protected_case() -> None:
    engine = LocalMemoryEngine()
    evidence_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="episode",
            content="An unrelated episodic note about the deployment window.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    worker = ConsolidationWorker(
        engine,
        [
            RegressionCase(
                id="must-survive",
                signature="critical protected fact",
                query="critical protected fact",
                expected_substring="must survive",
                protected=True,
            )
        ],
    )

    result = worker.run_job(
        ConsolidationJob(
            tenant_id=TENANT,
            signature="deployment-window",
            query="deployment window",
            candidate_subject="deployment window",
            candidate_predicate="is",
            candidate_object="unrelated",
            source_evidence_cids=[evidence_cid],
        )
    )

    # The protected regression can never retrieve "must survive", so the gate
    # must refuse to promote the candidate.
    assert result.promoted is False


def test_consolidation_corroboration_gate_requires_distinct_sources() -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="episode",
            content="The deploy window is Friday.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    gate_case = RegressionCase(
        id="deploy-window",
        signature="deploy-window",
        query="deploy window",
        expected_substring="Friday",
        protected=True,
    )
    worker = ConsolidationWorker(engine, [gate_case], min_corroboration=2)

    def job(cids: list[str]) -> ConsolidationJob:
        return ConsolidationJob(
            tenant_id=TENANT,
            signature="deploy-window",
            query="deploy window",
            candidate_subject="deploy window",
            candidate_predicate="is",
            candidate_object="Friday",
            source_evidence_cids=cids,
        )

    # A single source does not corroborate -> gate refuses to promote.
    single = worker.run_job(job([cid]))
    assert single.promoted is False
    assert any("corroboration" in failure for failure in single.failed_cases)

    # A second independent source satisfies §23.3 corroboration -> promotes.
    cid2 = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Deploy is confirmed for Friday.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    corroborated = worker.run_job(job([cid, cid2]))
    assert corroborated.promoted is True


def test_consolidation_default_corroboration_is_single_source() -> None:
    # Default min_corroboration=1 keeps single-source promotion working.
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="episode",
            content="The cache TTL is sixty seconds.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    gate_case = RegressionCase(
        id="cache-ttl",
        signature="cache-ttl",
        query="cache ttl",
        expected_substring="sixty seconds",
        protected=True,
    )
    worker = ConsolidationWorker(engine, [gate_case])
    result = worker.run_job(
        ConsolidationJob(
            tenant_id=TENANT,
            signature="cache-ttl",
            query="cache ttl",
            candidate_subject="cache ttl",
            candidate_predicate="is",
            candidate_object="sixty seconds",
            source_evidence_cids=[cid],
        )
    )
    assert result.promoted is True


def test_consolidation_cadence_throttles_rapid_resignature() -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="episode",
            content="The build server is online.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    gate_case = RegressionCase(
        id="build-server",
        signature="build-server",
        query="build server",
        expected_substring="online",
        protected=True,
    )
    now = [datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)]
    worker = ConsolidationWorker(
        engine,
        [gate_case],
        consolidation_min_interval_seconds=60.0,
        clock=lambda: now[0],
    )
    job = ConsolidationJob(
        tenant_id=TENANT,
        signature="build-server",
        query="build server",
        candidate_subject="build server",
        candidate_predicate="is",
        candidate_object="online",
        source_evidence_cids=[cid],
    )

    first = worker.run_job(job)
    assert first.promoted is True
    # A second run inside the anti-thrash window is throttled, not re-promoted.
    second = worker.run_job(job)
    assert second.promoted is False
    assert any("anti-thrash" in failure for failure in second.failed_cases)
    # Once the interval elapses, consolidation runs again.
    now[0] = now[0] + timedelta(seconds=61)
    third = worker.run_job(job)
    assert third.promoted is True
