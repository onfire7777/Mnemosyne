"""Unit and integration tests for chronological entity state trajectories and relation supersession."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.episodic_facts import (
    EntityAttributeTrajectory,
    TrajectoryStep,
    build_attribute_trajectories,
    build_attribute_trajectory,
    extract_episodic_facts,
)
from mnemosyne.models import Assertion, Evidence, Relation, parse_dt
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.sqlite_engine import SqliteEngine


def test_multi_step_trajectory_ordering() -> None:
    """Multi-step trajectories are ordered chronologically and tag latest as (CURRENT)."""
    t1 = datetime(2020, 1, 1, tzinfo=UTC)
    t2 = datetime(2022, 6, 1, tzinfo=UTC)
    t3 = datetime(2024, 3, 15, tzinfo=UTC)

    # Pass in shuffled/unordered order to verify chronological sorting
    assertions = [
        Assertion(
            tenant_id="t1",
            subject="user",
            predicate="residence",
            object="Portland",
            valid_from=t3,
            status="active",
            source_evidence_cids=["cid3"],
        ),
        Assertion(
            tenant_id="t1",
            subject="user",
            predicate="residence",
            object="Sacramento",
            valid_from=t1,
            valid_to=t2,
            status="superseded",
            source_evidence_cids=["cid1"],
        ),
        Assertion(
            tenant_id="t1",
            subject="user",
            predicate="residence",
            object="San Diego",
            valid_from=t2,
            valid_to=t3,
            status="superseded",
            source_evidence_cids=["cid2"],
        ),
    ]

    trajectory = build_attribute_trajectory(assertions, "user", "residence")

    assert isinstance(trajectory, EntityAttributeTrajectory)
    assert all(isinstance(step, TrajectoryStep) for step in trajectory.steps)
    assert trajectory.entity == "user"
    assert trajectory.attribute == "residence"
    assert len(trajectory.steps) == 3

    # Check order
    assert trajectory.steps[0].value == "Sacramento"
    assert trajectory.steps[0].valid_from == t1
    assert trajectory.steps[0].status == "SUPERSEDED"
    assert trajectory.steps[0].evidence_cids == ("cid1",)

    assert trajectory.steps[1].value == "San Diego"
    assert trajectory.steps[1].valid_from == t2
    assert trajectory.steps[1].status == "SUPERSEDED"
    assert trajectory.steps[1].evidence_cids == ("cid2",)

    assert trajectory.steps[2].value == "Portland"
    assert trajectory.steps[2].valid_from == t3
    assert trajectory.steps[2].status == "CURRENT"
    assert trajectory.steps[2].evidence_cids == ("cid3",)

    # Current value and current property
    assert trajectory.current_value == "Portland"
    assert trajectory.current is not None
    assert trajectory.current.value == "Portland"

    # as_of point-in-time state lookup
    as_of_2021 = trajectory.as_of(datetime(2021, 1, 1, tzinfo=UTC))
    assert as_of_2021 is not None and as_of_2021.value == "Sacramento"

    as_of_2023 = trajectory.as_of(datetime(2023, 1, 1, tzinfo=UTC))
    assert as_of_2023 is not None and as_of_2023.value == "San Diego"

    as_of_2025 = trajectory.as_of(datetime(2025, 1, 1, tzinfo=UTC))
    assert as_of_2025 is not None and as_of_2025.value == "Portland"

    # format_trajectory
    formatted = trajectory.format_trajectory()
    assert (
        formatted
        == "Sacramento (2020-01-01) -> San Diego (2022-06-01) -> Portland (2024-03-15, CURRENT)"
    )


def test_single_step_trajectory() -> None:
    """A single assertion forms a 1-step trajectory marked (CURRENT)."""
    t1 = datetime(2021, 9, 1, tzinfo=UTC)
    assertions = [
        Assertion(
            tenant_id="t1",
            subject="user",
            predicate="works_at",
            object="Google",
            valid_from=t1,
            status="active",
        ),
    ]

    trajectory = build_attribute_trajectory(assertions, "user", "works_at")
    assert len(trajectory.steps) == 1
    assert trajectory.steps[0].value == "Google"
    assert trajectory.steps[0].status == "CURRENT"
    assert trajectory.current_value == "Google"
    assert trajectory.format_trajectory() == "Google (2021-09-01, CURRENT)"


def test_empty_trajectory() -> None:
    """No matching assertions returns an empty trajectory structure."""
    trajectory = build_attribute_trajectory([], "user", "car")
    assert trajectory.entity == "user"
    assert trajectory.attribute == "car"
    assert trajectory.steps == ()
    assert trajectory.current_value is None
    assert trajectory.current is None
    assert trajectory.format_trajectory() == ""


def test_engine_relation_supersession_synchronization() -> None:
    """When an assertion is superseded in upsert_assertion, corresponding relations receive valid_to."""
    engine = LocalMemoryEngine()
    tenant_id = "test-tenant"
    branch = "main"

    t1 = datetime(2020, 1, 1, tzinfo=UTC)
    t2 = datetime(2024, 1, 1, tzinfo=UTC)

    # 1. Add initial residence assertion and relations
    initial_assertion = Assertion(
        tenant_id=tenant_id,
        branch=branch,
        subject="user",
        predicate="residence",
        object="Sacramento",
        valid_from=t1,
        status="active",
    )
    engine.upsert_assertion(initial_assertion, branch=branch)

    rel_lives = Relation(
        tenant_id=tenant_id,
        branch=branch,
        source="user",
        predicate="lives_in",
        target="Sacramento",
        valid_from=t1,
        valid_to=None,
    )
    rel_residence = Relation(
        tenant_id=tenant_id,
        branch=branch,
        source="user",
        predicate="residence",
        target="Sacramento",
        valid_from=t1,
        valid_to=None,
    )
    engine.add_relation(rel_lives, branch=branch)
    engine.add_relation(rel_residence, branch=branch)

    # Verify initial relations have valid_to = None
    stored_relations = [
        r
        for r in engine.relations.values()
        if r.tenant_id == tenant_id and r.source == "user" and r.target == "Sacramento"
    ]
    assert len(stored_relations) == 2
    for r in stored_relations:
        assert r.valid_to is None

    # 2. Upsert newer assertion superseding Sacramento
    incoming_assertion = Assertion(
        tenant_id=tenant_id,
        branch=branch,
        subject="user",
        predicate="residence",
        object="San Diego",
        valid_from=t2,
        status="active",
    )
    engine.upsert_assertion(incoming_assertion, branch=branch)

    # 3. Verify relations are synchronized with valid_to = t2
    for r in stored_relations:
        assert r.valid_to == t2


def test_graph_ppr_prevents_diffusion_leakage_after_supersession() -> None:
    """Superseded relations do not leak PPR diffusion mass on current/future queries."""
    engine = LocalMemoryEngine()
    tenant_id = "test-tenant-ppr"
    branch = "main"

    t_old = datetime(2020, 1, 1, tzinfo=UTC)
    t_new = datetime(2024, 1, 1, tzinfo=UTC)

    ev1 = engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id="u1",
            actor="user",
            source_type="conversation",
            content="I lived in Sacramento.",
        )
    )
    ev2 = engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id="u1",
            actor="user",
            source_type="conversation",
            content="Sacramento is in California.",
        )
    )
    ev3 = engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id="u1",
            actor="user",
            source_type="conversation",
            content="I moved to San Diego.",
        )
    )

    # Initial state: User lives in Sacramento, Sacramento in California
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant_id,
            branch=branch,
            subject="user",
            predicate="residence",
            object="Sacramento",
            valid_from=t_old,
            source_evidence_cids=[ev1],
        ),
        branch=branch,
    )
    engine.add_relation(
        Relation(
            tenant_id=tenant_id,
            branch=branch,
            source="user",
            predicate="lives_in",
            target="Sacramento",
            valid_from=t_old,
            source_evidence_cids=[ev1],
        ),
        branch=branch,
    )
    engine.add_relation(
        Relation(
            tenant_id=tenant_id,
            branch=branch,
            source="Sacramento",
            predicate="located_in",
            target="California",
            valid_from=t_old,
            source_evidence_cids=[ev2],
        ),
        branch=branch,
    )

    # User moves to San Diego
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant_id,
            branch=branch,
            subject="user",
            predicate="residence",
            object="San Diego",
            valid_from=t_new,
            source_evidence_cids=[ev3],
        ),
        branch=branch,
    )
    engine.add_relation(
        Relation(
            tenant_id=tenant_id,
            branch=branch,
            source="user",
            predicate="lives_in",
            target="San Diego",
            valid_from=t_new,
            source_evidence_cids=[ev3],
        ),
        branch=branch,
    )

    # Query graph as of 2024-06-01 (post-move):
    post_move_time = datetime(2024, 6, 1, tzinfo=UTC)
    hits_current = engine.graph_ppr(
        seeds=["user"],
        k=10,
        as_of=post_move_time,
        tenant_id=tenant_id,
        branch=branch,
    )
    hit_texts_current = [h.text.lower() for h in hits_current]

    # San Diego must be present, Sacramento must NOT be present (no PPR diffusion mass leak)
    assert any("san diego" in t for t in hit_texts_current)
    assert not any("sacramento" in t for t in hit_texts_current)

    # Query graph as of 2021-06-01 (historical point-in-time):
    historical_time = datetime(2021, 6, 1, tzinfo=UTC)
    hits_hist = engine.graph_ppr(
        seeds=["user"],
        k=10,
        as_of=historical_time,
        tenant_id=tenant_id,
        branch=branch,
    )
    hit_texts_hist = [h.text.lower() for h in hits_hist]

    # Sacramento must be present historically, San Diego must NOT be present
    assert any("sacramento" in t for t in hit_texts_hist)
    assert not any("san diego" in t for t in hit_texts_hist)


def test_historical_superseded_relation_synchronization() -> None:
    """An out-of-order older assertion arriving after current state gets synchronized with valid_to."""
    engine = LocalMemoryEngine()
    tenant_id = "test-tenant-hist"
    branch = "main"

    t_new = datetime(2024, 1, 1, tzinfo=UTC)
    t_old = datetime(2020, 1, 1, tzinfo=UTC)

    # 1. First insert current state: San Diego in 2024
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant_id,
            branch=branch,
            subject="user",
            predicate="residence",
            object="San Diego",
            valid_from=t_new,
        ),
        branch=branch,
    )

    # 2. Also register relation for Sacramento (2020)
    engine.add_relation(
        Relation(
            tenant_id=tenant_id,
            branch=branch,
            source="user",
            predicate="lives_in",
            target="Sacramento",
            valid_from=t_old,
            valid_to=None,
        ),
        branch=branch,
    )

    # 3. Older assertion arrives out of order: Sacramento in 2020
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant_id,
            branch=branch,
            subject="user",
            predicate="residence",
            object="Sacramento",
            valid_from=t_old,
        ),
        branch=branch,
    )

    # Verify Sacramento relation valid_to is synchronized to current.valid_from (2024-01-01)
    sac_relations = [
        r
        for r in engine.relations.values()
        if r.tenant_id == tenant_id and r.source == "user" and r.target == "Sacramento"
    ]
    assert len(sac_relations) == 1
    assert sac_relations[0].valid_to == t_new


def test_expired_or_superseded_single_step_trajectory() -> None:
    """A single superseded or expired assertion is marked SUPERSEDED and has no current value."""
    t1 = datetime(2020, 1, 1, tzinfo=UTC)
    t2 = datetime(2022, 1, 1, tzinfo=UTC)
    assertion = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Sacramento",
        valid_from=t1,
        valid_to=t2,
        status="superseded",
    )
    trajectory = build_attribute_trajectory([assertion], "user", "residence")
    assert len(trajectory.steps) == 1
    assert trajectory.steps[0].status == "SUPERSEDED"
    assert trajectory.current is None
    assert trajectory.current_value is None
    assert "CURRENT" not in trajectory.format_trajectory()
    assert trajectory.format_trajectory() == "Sacramento (2020-01-01)"


def test_timezone_naive_and_aware_sorting_in_trajectory() -> None:
    """Trajectories sort without TypeError when assertions mix naive and aware timestamps."""
    a1 = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Sacramento",
        valid_from=datetime(2020, 1, 1),  # naive
    )
    a2 = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="San Diego",
        valid_from=datetime(2022, 1, 1, tzinfo=UTC),  # aware
    )
    trajectory = build_attribute_trajectory([a2, a1], "user", "residence")
    assert len(trajectory.steps) == 2
    assert trajectory.steps[0].value == "Sacramento"
    assert trajectory.steps[1].value == "San Diego"
    assert trajectory.steps[1].status == "CURRENT"


def test_attribute_trajectories_alias_and_casing_normalization() -> None:
    """build_attribute_trajectories groups aliases and handles case insensitivity."""
    assertions = [
        Assertion(
            tenant_id="t1",
            subject="User",  # uppercase
            predicate="works_at",
            object="Google",
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            status="superseded",
        ),
        Assertion(
            tenant_id="t1",
            subject="user",  # lowercase
            predicate="employed_by",  # alias
            object="Meta",
            valid_from=datetime(2022, 1, 1, tzinfo=UTC),
            status="active",
        ),
        Assertion(
            tenant_id="t1",
            subject="user",
            predicate="education",
            object="MIT",
            valid_from=datetime(2016, 9, 1, tzinfo=UTC),
            status="superseded",
        ),
        Assertion(
            tenant_id="t1",
            subject="USER",  # uppercase
            predicate="graduated_from",  # alias
            object="Stanford",
            valid_from=datetime(2020, 6, 1, tzinfo=UTC),
            status="active",
        ),
    ]

    trajectories = build_attribute_trajectories(assertions)
    by_attr = {t.attribute: t for t in trajectories}
    assert "works_at" in by_attr
    assert "education" in by_attr
    assert len(by_attr["works_at"].steps) == 2
    assert by_attr["works_at"].entity == "user"
    assert by_attr["works_at"].steps[0].value == "Google"
    assert by_attr["works_at"].steps[1].value == "Meta"
    assert by_attr["works_at"].current_value == "Meta"

    assert len(by_attr["education"].steps) == 2
    assert by_attr["education"].entity == "user"
    assert by_attr["education"].steps[0].value == "MIT"
    assert by_attr["education"].steps[1].value == "Stanford"


def test_sqlite_engine_relation_supersession_parity(tmp_path: Path) -> None:
    """SqliteEngine synchronizes relation valid_to when assertions supersede."""
    engine = SqliteEngine(tmp_path / "sqlite-store")
    tenant_id = "test-tenant"
    branch = "main"

    t_old = datetime(2020, 1, 1, tzinfo=UTC)
    t_new = datetime(2024, 1, 1, tzinfo=UTC)

    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id="u1",
            actor="user",
            source_type="chat",
            branch=branch,
            content="Evidence",
            access_policy={"tenant": tenant_id},
        )
    )

    # Add relation for Sacramento (2020)
    engine.add_relation(
        Relation(
            tenant_id=tenant_id,
            branch=branch,
            source="user",
            predicate="lives_in",
            target="Sacramento",
            valid_from=t_old,
            valid_to=None,
            source_evidence_cids=[cid],
        ),
        branch=branch,
    )

    # Add initial assertion Sacramento (2020)
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant_id,
            branch=branch,
            subject="user",
            predicate="residence",
            object="Sacramento",
            valid_from=t_old,
            source_evidence_cids=[cid],
        ),
        branch=branch,
    )

    # Supersede with newer assertion San Diego (2024)
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant_id,
            branch=branch,
            subject="user",
            predicate="residence",
            object="San Diego",
            valid_from=t_new,
            source_evidence_cids=[cid],
        ),
        branch=branch,
    )

    # Query relations from SQLite table
    exported = engine.export_tenant(tenant_id)
    sac_rel = [
        r for r in exported.get("relations", []) if r.get("target") == "Sacramento"
    ]
    assert len(sac_rel) == 1
    assert sac_rel[0].get("valid_to") is not None

    # Test direct _sync_relation_supersession call on SqliteEngine
    t_sync = datetime(2021, 6, 1, tzinfo=UTC)
    engine._sync_relation_supersession(
        tenant_id, branch, "user", "lives_in", "Sacramento", t_sync
    )
    exported2 = engine.export_tenant(tenant_id)
    sac_rel2 = [
        r for r in exported2.get("relations", []) if r.get("target") == "Sacramento"
    ]
    assert parse_dt(sac_rel2[0].get("valid_to")) == t_sync


def test_postgres_engine_relation_supersession_signature() -> None:
    """PostgresEngine exposes _sync_relation_supersession matching LocalMemoryEngine parity."""
    assert hasattr(PostgresEngine, "_sync_relation_supersession")


def test_hypothetical_assertions_excluded_from_trajectories() -> None:
    """Hypothetical assertions are excluded from build_attribute_trajectories and build_attribute_trajectory."""
    text = "user: In 2020, I lived in Boston. Suppose I moved to Chicago in 2024."
    facts = extract_episodic_facts(text, speaker_role="user")

    # Group trajectories should exclude hypothetical Chicago move
    trajs = build_attribute_trajectories(facts.assertions)
    for t in trajs:
        assert t.current_value != "Chicago"
        for s in t.steps:
            assert s.value != "Chicago"

    # Direct trajectory call should also filter out hypothetical Chicago
    traj = build_attribute_trajectory(facts.assertions, "user", "residence")
    assert len(traj.steps) == 1
    assert traj.steps[0].value == "Boston"
    assert traj.steps[0].status == "CURRENT"
    assert traj.current_value == "Boston"
    assert traj.format_trajectory() == "Boston (2020-01-01, CURRENT)"

    # If all assertions are hypothetical, empty trajectory is returned
    hypo_assertions = [
        Assertion(
            tenant_id="t1",
            subject="user",
            predicate="residence",
            object="Paris",
            qualifiers={"is_hypothetical": True},
        )
    ]
    empty_traj = build_attribute_trajectory(hypo_assertions, "user", "residence")
    assert empty_traj.steps == ()
    assert empty_traj.current_value is None


def test_retracted_and_quarantined_assertions_status_tracking() -> None:
    """Retracted and quarantined assertions are never tagged as CURRENT and their current_value is None."""
    # Retracted assertion
    a_ret = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Denver",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
        status="retracted",
    )
    traj_ret = build_attribute_trajectory([a_ret], "user", "residence")
    assert len(traj_ret.steps) == 1
    assert traj_ret.steps[0].status == "RETRACTED"
    assert traj_ret.current is None
    assert traj_ret.current_value is None
    assert "CURRENT" not in traj_ret.format_trajectory()

    # Quarantined assertion
    a_quar = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Miami",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
        status="quarantined",
    )
    traj_quar = build_attribute_trajectory([a_quar], "user", "residence")
    assert len(traj_quar.steps) == 1
    assert traj_quar.steps[0].status == "QUARANTINED"
    assert traj_quar.current is None
    assert traj_quar.current_value is None
    assert "CURRENT" not in traj_quar.format_trajectory()


def test_multi_step_trajectory_with_retracted_final_step() -> None:
    """When a subsequent assertion is retracted, earlier active assertion remains CURRENT."""
    t1 = datetime(2020, 1, 1, tzinfo=UTC)
    t2 = datetime(2024, 1, 1, tzinfo=UTC)

    # Earlier active assertion, later retracted assertion
    a_active = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Sacramento",
        valid_from=t1,
        status="active",
    )
    a_retracted = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Denver",
        valid_from=t2,
        status="retracted",
    )

    traj = build_attribute_trajectory([a_active, a_retracted], "user", "residence")
    assert len(traj.steps) == 2
    assert traj.steps[0].value == "Sacramento"
    assert traj.steps[0].status == "CURRENT"
    assert traj.steps[1].value == "Denver"
    assert traj.steps[1].status == "RETRACTED"

    assert traj.current_value == "Sacramento"
    assert traj.current is not None
    assert traj.current.value == "Sacramento"
