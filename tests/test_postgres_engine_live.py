from __future__ import annotations

import os
import json
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB, ConsolidationWorker
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.queue import InProcessQueue, QueueWorker


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
            trust_tier=0,
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
            trust_tier=0,
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


def test_postgres_engine_live_shared_contract_parity() -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-contract-live-{uuid4()}"
    other_tenant = f"tenant-contract-other-{uuid4()}"
    user = "user-live-contract"

    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="contract",
            content="Live contract status moved from draft to shipped.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    first_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="live contract status",
            predicate="is",
            object="draft",
            source_evidence_cids=[cid],
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    second_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="live contract status",
            predicate="is",
            object="shipped",
            source_evidence_cids=[cid],
            valid_from=datetime(2026, 2, 1, tzinfo=UTC),
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    jan = engine.as_of("live contract status", "is", datetime(2026, 1, 15, tzinfo=UTC), tenant_id=tenant)
    feb = engine.as_of("live contract status", "is", datetime(2026, 2, 15, tzinfo=UTC), tenant_id=tenant)
    by_id = {item["id"]: item for item in engine.export_tenant(tenant)["assertions"]}
    isolated = engine.retrieve("live contract status shipped", other_tenant)

    branch = f"candidate-contract-{uuid4()}"
    engine.branch(branch, tenant_id=tenant)
    branch_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="branch-only parity",
            predicate="proves",
            object="tenant scoped merge",
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )
    main_before = engine.retrieve("branch-only parity", tenant)
    branch_result = engine.retrieve("branch-only parity", tenant, branch=branch)
    merge_report = engine.merge(branch, tenant_id=tenant)
    main_after = engine.retrieve("branch-only parity", tenant)
    engine.discard(branch, tenant_id=tenant)

    assert jan[-1].id == first_id
    assert feb[-1].id == second_id
    assert by_id[first_id]["status"] == "superseded"
    assert by_id[first_id]["superseded_by"] == second_id
    assert by_id[second_id]["status"] == "active"
    assert not isolated.hits
    assert all(hit.id != branch_id for hit in main_before.hits)
    assert any(hit.id == branch_id for hit in branch_result.hits)
    assert merge_report.assertions_added >= 1
    assert any(hit.id == branch_id for hit in main_after.hits)


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
        "0",
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
        "0",
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
    legal = run_postgres_cli(
        "capture",
        "--tenant",
        tenant,
        "--user",
        user,
        "--source-type",
        "legal",
        "--content",
        "Hard-delete this live Postgres evidence.",
        "--trust-tier",
        "0",
    )
    hard_deleted = run_postgres_cli(
        "forget",
        "--tenant",
        tenant,
        "--cid",
        legal["cid"],
        "--erasure-mode",
        "hard_delete_legal",
    )
    after_delete = run_postgres_cli("export", "--tenant", tenant)

    assert asserted["id"]
    assert search["explain"]["channels"]["postgres_dense"] >= 1
    assert search["explain"]["channels"]["postgres_lexical"] >= 1
    assert deep["explain"]["channels"]["postgres_graph_ppr"] >= 1
    assert branch_search["hits"]
    assert hard_deleted["erasure_mode"] == "hard_delete_legal"
    assert all(item["cid"] != legal["cid"] for item in after_delete["evidence"])
    assert any(item["statement"] == "Prefer CLI-first memory workflows." for item in exported["preferences"])


def test_postgres_mcp_backend_live_smoke() -> None:
    tenant = f"tenant-mcp-live-{uuid4()}"
    user = "user-mcp-live"
    server = MnemosyneMcpServer(backend="postgres", postgres_dsn=live_dsn())

    capture = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "tenant_id": tenant,
                    "user_id": user,
                    "actor": "user",
                    "source_type": "mcp-live",
                    "content": "Postgres MCP backend captures production memory.",
                    "trust_tier": 0,
                },
            },
        }
    )
    search = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"tenant_id": tenant, "query": "Postgres MCP backend production memory"},
            },
        }
    )

    assert capture["result"]["isError"] is False
    assert search["result"]["isError"] is False
    assert search["result"]["structuredContent"]["explain"]["channels"]["postgres_dense"] >= 1
    assert search["result"]["structuredContent"]["hits"][0]["provenance"] == [capture["result"]["structuredContent"]["cid"]]


def test_postgres_cli_ingests_file_with_c2pa_verifier(tmp_path) -> None:
    tenant = f"tenant-cli-c2pa-live-{uuid4()}"
    user = "user-cli-c2pa-live"
    asset = tmp_path / "capture.bin"
    asset.write_bytes(b"postgres binary capture")
    verifier_stub = tmp_path / "c2pa-ok.py"
    verifier_stub.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "print(json.dumps({'active_manifest': 'manifest-1', 'claim_generator': 'issuer-a'}))",
            ]
        ),
        encoding="utf-8",
    )
    verifier_stub.chmod(0o755)

    ingested = run_postgres_cli(
        "--c2pa-tool",
        str(verifier_stub),
        "--trusted-provenance-issuer",
        "issuer-a",
        "ingest",
        "--tenant",
        tenant,
        "--user",
        user,
        "--actor",
        "external",
        "--source-type",
        "camera",
        "--file",
        str(asset),
        "--modality",
        "binary",
        "--media-type",
        "application/octet-stream",
        "--metadata",
        json.dumps({"description": "Postgres binary camera capture."}),
        "--trust-tier",
        "5",
    )
    exported = run_postgres_cli("export", "--tenant", tenant)
    evidence = next(item for item in exported["evidence"] if item["cid"] == ingested["cid"])
    search = run_postgres_cli("search", "--tenant", tenant, "--query", "binary camera capture")

    assert ingested["content_pointer"] is not None
    assert ingested["trust_tier"] == 3
    assert ingested["provenance"]["trusted"] is True
    assert evidence["content_pointer"] == ingested["content_pointer"]
    assert evidence["content"] == "Postgres binary camera capture."
    assert evidence["metadata"]["derived_text_sources"] == ["description"]
    assert evidence["metadata"]["provenance_decision"]["manifest"]["c2pa"]["claim_generator"] == "issuer-a"
    assert search["hits"][0]["id"] == ingested["cid"]


def test_postgres_gated_consolidation_promotes_direct_user_fact_live() -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-gate-live-{uuid4()}"
    user = "user-gate-live"
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    result = pipeline.ingest(
        IngestRequest(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Postgres gate fact is tenant aware.",
        )
    )
    worker = QueueWorker(
        queue,
        {
            CONSOLIDATE_EVIDENCE_JOB: ConsolidationWorker(
                engine,
                gate_cases=[
                    RegressionCase(
                        "postgres-gate-smoke",
                        "postgres gate fact",
                        "Postgres gate fact",
                        "Postgres gate fact is tenant aware",
                        protected=True,
                    )
                ],
            ).run_queue_payload
        },
    )

    job = worker.run_once(CONSOLIDATE_EVIDENCE_JOB)
    search = engine.retrieve("Postgres gate fact", tenant)

    assert job is not None
    assert job.status == "complete"
    assert job.result["candidate_results"][0]["promoted"] is True
    assert any(hit.kind == "assertion" and hit.provenance == [result.cid] for hit in search.hits)
