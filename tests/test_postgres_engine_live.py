from __future__ import annotations

import os
import json
import subprocess
import sys
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


def run_postgres_cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "mnemosyne.cli", "--backend", "postgres", "--postgres-dsn", live_dsn(), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


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


def test_postgres_cli_backend_live_smoke() -> None:
    tenant = f"tenant-cli-live-{uuid4()}"
    user = "user-cli-live"

    captured = run_postgres_cli(
        "capture",
        "--tenant",
        tenant,
        "--user",
        user,
        "--source-type",
        "cli-live",
        "--content",
        "The CLI backend can use live Postgres retrieval.",
        "--trust-tier",
        "3",
    )
    asserted = run_postgres_cli(
        "assert",
        "--tenant",
        tenant,
        "--user",
        user,
        "--subject",
        "CLI backend",
        "--predicate",
        "uses",
        "--object",
        "live Postgres retrieval",
        "--evidence-cid",
        captured["cid"],
        "--confidence",
        "0.9",
        "--trust-tier",
        "3",
    )
    run_postgres_cli(
        "relation",
        "--tenant",
        tenant,
        "--source",
        "CLI backend",
        "--predicate",
        "uses",
        "--target",
        "Postgres",
        "--evidence-cid",
        captured["cid"],
    )
    run_postgres_cli(
        "preference",
        "--tenant",
        tenant,
        "--user",
        user,
        "--category",
        "tooling",
        "--statement",
        "Prefer CLI-first memory workflows.",
        "--explicit",
    )

    search = run_postgres_cli("search", "--tenant", tenant, "--query", "CLI backend Postgres retrieval")
    deep = run_postgres_cli("deep-search", "--tenant", tenant, "--query", "CLI backend")
    exported = run_postgres_cli("export", "--tenant", tenant)
    run_postgres_cli("branch", "--tenant", tenant, "--name", "cli-candidate")
    branch_search = run_postgres_cli("search", "--tenant", tenant, "--branch", "cli-candidate", "--query", "CLI backend Postgres")
    run_postgres_cli("discard", "--tenant", tenant, "--branch", "cli-candidate")

    assert asserted["id"]
    assert search["explain"]["channels"]["postgres_dense"] >= 1
    assert search["explain"]["channels"]["postgres_lexical"] >= 1
    assert deep["explain"]["channels"]["postgres_graph_ppr"] >= 1
    assert branch_search["hits"]
    assert any(item["statement"] == "Prefer CLI-first memory workflows." for item in exported["preferences"])
