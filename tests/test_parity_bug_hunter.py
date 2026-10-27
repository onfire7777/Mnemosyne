from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.sqlite_engine import SqliteEngine


def _live_dsn() -> str | None:
    return (
        os.environ.get("MNEMOSYNE_POSTGRES_TEST_DSN")
        or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    )


@pytest.fixture(params=["local", "sqlite", "postgres"])
def engine_bundle(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, str, str]:
    tenant = f"tenant-hunter-{request.param}-{uuid4()}"
    user = f"user-hunter-{request.param}"
    if request.param == "local":
        return LocalMemoryEngine(store_path=tmp_path / "local-store.json"), tenant, user
    if request.param == "sqlite":
        return SqliteEngine(tmp_path / "sqlite-store"), tenant, user
    dsn = _live_dsn()
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_TEST_DSN/MNEMOSYNE_POSTGRES_DSN is not set")
    pytest.importorskip("psycopg")
    engine = PostgresEngine(dsn)
    engine.ensure_tenant_and_branch(tenant, "main")
    return engine, tenant, user


def test_parity_graph_ppr_tenant_in_filter(engine_bundle: tuple[Any, str, str]) -> None:
    """When tenant_id is supplied via filt={'tenant_id': ...} with tenant_id=None,
    graph_ppr must return the relation hit across all backends."""
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="interview",
            content="Apples are deciduous orchard fruit.",
            access_policy={"tenant": tenant},
        )
    )
    engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="apple",
            predicate="classified_as",
            target="fruit",
            confidence=0.92,
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )

    hits = engine.graph_ppr(["apple"], 5, filt={"tenant_id": tenant})
    assert len(hits) >= 1, f"Expected at least 1 graph hit, got {len(hits)}"
    assert hits[0].kind == "relation"
    assert hits[0].metadata["source"] == "apple"
    assert hits[0].metadata["target"] == "fruit"


def test_parity_add_relation_update_fields(engine_bundle: tuple[Any, str, str]) -> None:
    """Updating a relation with the same ID must update source, predicate, target,
    valid_from, valid_to, and confidence consistently across all backends."""
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="doc",
            content="Evidence for relation updates.",
            access_policy={"tenant": tenant},
        )
    )
    rel_id = str(uuid4())
    t1 = datetime(2026, 2, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 2, 10, 0, 0, tzinfo=UTC)

    # Initial relation
    engine.add_relation(
        Relation(
            id=rel_id,
            tenant_id=tenant,
            source="node_alpha",
            predicate="initial_pred",
            target="node_beta",
            confidence=0.6,
            valid_from=t1,
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )

    # Update relation with new predicate, target, and confidence
    engine.add_relation(
        Relation(
            id=rel_id,
            tenant_id=tenant,
            source="node_alpha_v2",
            predicate="updated_pred",
            target="node_beta_v2",
            confidence=0.95,
            valid_from=t2,
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )

    exported = engine.export_tenant(tenant)
    relations = [r for r in exported["relations"] if r["id"] == rel_id]
    assert len(relations) == 1
    rel = relations[0]
    assert rel["predicate"] == "updated_pred", f"Expected updated predicate, got {rel['predicate']}"
    assert rel["source"] == "node_alpha_v2", f"Expected updated source, got {rel['source']}"
    assert rel["target"] == "node_beta_v2", f"Expected updated target, got {rel['target']}"
    assert pytest.approx(rel["confidence"]) == 0.95


def test_parity_as_of_identical_microsecond_timestamps(engine_bundle: tuple[Any, str, str]) -> None:
    """When multiple assertions have identical valid_from microsecond timestamps,
    as_of must return them in a deterministic order (valid_from, id) across all engines."""
    engine, tenant, user = engine_bundle
    sub = f"entity-{uuid4()}"
    pred = "state"
    t0 = datetime(2026, 3, 10, 14, 22, 33, 123456, tzinfo=UTC)

    u = uuid4().hex[:12]
    id_early = f"11111111-1111-4111-8111-{u}"
    id_late = f"22222222-2222-4222-8222-{u}"

    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="sensor",
            content="Entity state observation.",
            access_policy={"tenant": tenant},
        )
    )

    # Insert id_late first, then id_early
    engine.upsert_assertion(
        Assertion(
            id=id_late,
            tenant_id=tenant,
            user_id=user,
            subject=sub,
            predicate=pred,
            object="state_late",
            confidence=0.75,
            valid_from=t0,
            status="active",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            id=id_early,
            tenant_id=tenant,
            user_id=user,
            subject=sub,
            predicate=pred,
            object="state_early",
            confidence=0.85,
            valid_from=t0,
            status="active",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )

    results = engine.as_of(sub, pred, t0, tenant_id=tenant)
    assert len(results) == 2, f"Expected 2 assertions, got {len(results)}"
    # Tie-breaking on (valid_from, id) ensures id_early ('aaaa...') precedes id_late ('bbbb...')
    assert [item.id for item in results] == [id_early, id_late], (
        f"Backend {type(engine).__name__} returned {[item.id for item in results]} instead of {[id_early, id_late]}"
    )


def test_parity_search_handles_missing_tenant_id_in_filter(engine_bundle: tuple[Any, str, str]) -> None:
    """Vector and lexical search must safely handle missing tenant_id without KeyError."""
    engine, _, _ = engine_bundle
    vec_hits = engine.vector_search("hello world", 5, filt={})
    assert isinstance(vec_hits, list)
    lex_hits = engine.lexical_search("hello world", 5, filt={})
    assert isinstance(lex_hits, list)


def test_postgres_pool_resets_session_gucs_and_roles() -> None:
    """Postgres connection pool must reset session GUCs and SET ROLE on reuse."""
    dsn = _live_dsn()
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_TEST_DSN is not set")
    pytest.importorskip("psycopg")

    engine = PostgresEngine(dsn, require_safe_role=True)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            initial_user = cur.fetchone()[0]
            # Set a session-level configuration
            cur.execute("SET mnemosyne.test_leak_check = 'should_not_leak'")

    # Acquire a connection from the pool for reuse
    with engine.connect() as conn2:
        with conn2.cursor() as cur:
            cur.execute("SELECT current_setting('mnemosyne.test_leak_check', true)")
            val = cur.fetchone()[0]
            assert val is None or val == "", f"Session GUC leaked across connection reuse: {val!r}"
            cur.execute("SELECT current_user")
            assert cur.fetchone()[0] == initial_user
