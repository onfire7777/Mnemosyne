from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.postgres_engine import PostgresEngine


pytest.importorskip("psycopg")


def live_dsn() -> str:
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    return dsn


def test_postgres_engine_live_contract_smoke() -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-live-{uuid4()}"
    user = "user-live-smoke"

    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="smoke",
            content="Live Postgres contract smoke uses Postgres retrieval.",
            trust_tier=3,
            access_policy={"tenant": tenant},
        )
    )
    evidence = engine.get_evidence(tenant, cid)
    assert evidence is not None
    assert evidence.tenant_id == tenant
    assert evidence.user_id == user
    assert evidence.content.startswith("Live Postgres")

    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="runtime smoke",
            predicate="uses",
            object="Postgres retrieval",
            source_evidence_cids=[cid],
            confidence=0.9,
            status="active",
            trust_tier=3,
            access_policy={"tenant": tenant},
        )
    )
    result = engine.retrieve("runtime smoke Postgres", tenant)
    assert result.hits
    assert result.explain["channels"]["postgres_lexical"] >= 1
    assert result.explain["channels"]["postgres_dense"] >= 1
    assert result.explain["adapters"]["embedding_dims"] == 1024

    as_of = engine.as_of("runtime smoke", "uses", datetime.now(UTC), tenant_id=tenant)
    assert as_of and as_of[-1].id == assertion_id

    engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="runtime smoke",
            predicate="uses",
            target="Postgres",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )
    deep = engine.deep_search("runtime smoke", tenant)
    assert deep.explain["channels"]["postgres_graph_ppr"] >= 1
    engine.branch("candidate-live", tenant_id=tenant)
    branch_result = engine.retrieve("runtime smoke Postgres", tenant, branch="candidate-live")
    assert branch_result.hits
    engine.discard("candidate-live", tenant_id=tenant)

    forgotten = engine.forget(tenant, cid)
    assert forgotten["erased"] is True
    exported = engine.export_tenant(tenant)
    assert exported["tenant_id"] == tenant
    assert exported["assertions"]
