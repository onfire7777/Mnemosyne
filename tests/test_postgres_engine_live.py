from __future__ import annotations

import os
import json
import shlex
import subprocess
import sys
import threading
from datetime import UTC, datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from mnemosyne.consolidation import (
    CONSOLIDATE_EVIDENCE_JOB,
    CommandCandidateExtractor,
    CommandEntityResolver,
    CommandEvidenceSummarizer,
    ConsolidationWorker,
)
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.jobs import (
    CALIBRATE_JOB,
    EVAL_SUITE_JOB,
    LIFECYCLE_SWEEP_JOB,
    OBSERVABILITY_SNAPSHOT_JOB,
    PROJECTION_RECOMPUTE_JOB,
    RuntimeJobHandlers,
)
from mnemosyne.media import MEDIA_EXTRACT_JOB, MediaExtractionResult
from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.postgres_engine import PostgresEngine, _cid_to_bytes, _stable_uuid
from mnemosyne.queue import InProcessQueue, PostgresQueue, QueueWorker
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.storage import LocalObjectStore


pytest.importorskip("psycopg")


def live_dsn() -> str:
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    return dsn


def run_postgres_cli_raw(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mnemosyne.cli", "--backend", "postgres", "--postgres-dsn", live_dsn(), *args],
        check=False,
        text=True,
        capture_output=True,
    )


def run_postgres_cli(*args: str) -> dict:
    result = run_postgres_cli_raw(*args)
    result.check_returncode()
    return json.loads(result.stdout)


def fake_command_retrieval_provider(tmp_path: Path) -> tuple[str, Path]:
    script = tmp_path / "command-retrieval-provider.py"
    state = tmp_path / "command-retrieval-requests.json"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "state = pathlib.Path(sys.argv[1])",
                "request = json.loads(sys.stdin.read())",
                "requests = json.loads(state.read_text()) if state.exists() else []",
                "requests.append(request)",
                "state.write_text(json.dumps(requests, sort_keys=True))",
                "role = request.get('role')",
                "if role == 'graph_ppr':",
                "    hit = {'id': 'graph-hit-live', 'kind': 'relation', 'text': 'command graph retrieval reached Apache AGE wrapper', 'score': 0.93, 'channel': 'command_graph_ppr', 'metadata': {'source': 'Command graph', 'predicate': 'uses', 'target': 'Apache AGE'}}",
                "else:",
                "    hit = {'id': 'lexical-hit-live', 'kind': 'evidence', 'text': 'command lexical retrieval reached ParadeDB BM25 wrapper', 'score': 0.91, 'channel': 'command_lexical', 'metadata': {'source_type': 'command-lexical'}}",
                "print(json.dumps({'hits': [hit]}))",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return " ".join(shlex.quote(item) for item in (sys.executable, str(script), str(state))), state


def start_fake_retrieval_provider(*, malformed_embedding: bool = False) -> tuple[ThreadingHTTPServer, str, dict[str, list[dict]]]:
    calls: dict[str, list[dict]] = {"embedding": [], "reranker": []}

    def vector_for(text: str) -> list[float]:
        vector = [0.0] * 1024
        normalized = text.lower()
        if "preferred by http reranker" in normalized:
            vector[0] = 1.0
        elif "baseline evidence" in normalized:
            vector[1] = 1.0
        else:
            vector[0] = 0.8
            vector[1] = 0.2
        return vector

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler uses this method name.
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            authorization = self.headers.get("Authorization")
            if self.path == "/embed":
                calls["embedding"].append({"payload": payload, "authorization": authorization})
                body = {"embedding": [0.0] * 1024} if malformed_embedding else {"data": [{"embedding": vector_for(str(payload.get("input", "")))}]}
            elif self.path == "/rerank":
                documents = payload.get("documents")
                assert isinstance(documents, list)
                calls["reranker"].append({"payload": payload, "authorization": authorization})
                body = {
                    "results": [
                        {
                            "index": index,
                            "relevance_score": 50.0 if "preferred by http reranker" in str(document).lower() else 0.1,
                        }
                        for index, document in enumerate(documents)
                    ]
                }
            else:
                self.send_response(404)
                self.end_headers()
                return
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}", calls


def test_postgres_queue_lifecycle_and_tenant_isolation_live() -> None:
    tenant = f"tenant-queue-live-{uuid4()}"
    other_tenant = f"tenant-queue-other-{uuid4()}"
    queue = PostgresQueue(live_dsn(), tenant_id=tenant)
    other_queue = PostgresQueue(live_dsn(), tenant_id=other_tenant)

    enqueued = queue.enqueue(
        CALIBRATE_JOB,
        {"tenant_id": tenant, "scores": [0.1, 0.2, 0.3], "target_coverage": 0.9},
        max_attempts=2,
    )
    assert queue.snapshot()["queued"] == 1
    assert other_queue.lease() is None

    leased = queue.lease(CALIBRATE_JOB)
    assert leased is not None
    assert leased.id == enqueued.id
    assert leased.status == "running"
    assert leased.attempts == 1
    leased.result = {"ok": True}
    queue.complete(leased.id)

    jobs = queue.jobs
    assert jobs[leased.id].status == "complete"
    assert jobs[leased.id].result == {"ok": True}
    assert queue.snapshot()["complete"] == 1
    assert other_queue.snapshot() == {}


def test_postgres_runtime_helper_public_paths_live(tmp_path) -> None:
    tenant = f"tenant-runtime-helper-{uuid4()}"
    other_tenant = f"tenant-runtime-helper-other-{uuid4()}"
    branch = f"helper-{uuid4()}"
    dsn = live_dsn()
    engine = PostgresEngine(dsn)

    engine.ensure_tenant_and_branch(tenant, branch=branch, kind="scratch")
    engine.ensure_tenant_and_branch(tenant, branch=branch, kind="scratch")
    matching_branches = [
        row
        for row in engine.export_all()["branches"]
        if row["tenant_id"] == tenant and row["name"] == branch
    ]
    assert len(matching_branches) == 1
    assert matching_branches[0]["kind"] == "scratch"
    assert matching_branches[0]["from_branch"] is None

    queue = PostgresQueue(dsn, tenant_id=tenant)
    other_queue = PostgresQueue(dsn, tenant_id=other_tenant)
    queue.ensure_schema()
    first = queue.enqueue("runtime-helper-a", {"tenant_id": tenant, "order": 1})
    second = queue.enqueue("runtime-helper-b", {"tenant_id": tenant, "order": 2})
    listed = {job.id: job for job in queue.list_jobs()}

    assert set(listed) == {first.id, second.id}
    assert listed[first.id].payload["order"] == 1
    assert listed[second.id].payload["order"] == 2
    assert other_queue.list_jobs() == []

    store_path = tmp_path / "mnemosyne.json"
    runtime_state = RuntimeState.from_store_path(store_path)
    assert runtime_state is not None
    assert runtime_state.path == tmp_path / "mnemosyne.json.runtime.json"
    assert RuntimeState.from_store_path(None) is None


def test_postgres_queue_cli_enqueue_and_drain_live() -> None:
    tenant = f"tenant-queue-cli-{uuid4()}"
    payload = {
        "tenant_id": tenant,
        "scores": [0.2, 0.4, 0.8],
        "target_coverage": 0.9,
        "confidence": 0.35,
        "prediction_set_size": 2,
    }
    enqueued = run_postgres_cli(
        "--queue-backend",
        "postgres",
        "--queue-tenant",
        tenant,
        "queue-enqueue",
        "--kind",
        CALIBRATE_JOB,
        "--payload",
        json.dumps(payload),
    )
    drained = run_postgres_cli(
        "--queue-backend",
        "postgres",
        "--queue-tenant",
        tenant,
        "queue-drain",
        "--kind",
        CALIBRATE_JOB,
        "--limit",
        "1",
    )
    after = run_postgres_cli("--queue-backend", "postgres", "--queue-tenant", tenant, "queue-snapshot")

    assert enqueued["queue"]["queued"] == 1
    assert drained["jobs"][0]["status"] == "complete"
    assert drained["jobs"][0]["result"]["kind"] == "calibrate"
    assert drained["jobs"][0]["result"]["details"]["tenant_id"] == tenant
    assert after["queue"]["complete"] == 1


def test_postgres_queue_worker_drains_maintenance_handlers_live() -> None:
    tenant = f"tenant-queue-maintenance-{uuid4()}"
    user = f"user-queue-maintenance-{uuid4()}"
    engine = PostgresEngine(live_dsn())
    queue = PostgresQueue(live_dsn(), tenant_id=tenant)
    handlers = RuntimeJobHandlers(engine, queue)
    worker = QueueWorker(queue, handlers.handlers())
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="live-test",
            content="Postgres queue projection recompute evidence.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="Postgres queue maintenance",
            predicate="covers",
            object="projection recompute",
            confidence=0.9,
            source_evidence_cids=[cid],
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    queue.enqueue(
        CALIBRATE_JOB,
        {
            "tenant_id": tenant,
            "memory_type": "fact",
            "scores": [0.2, 0.4, 0.8],
            "confidence": 0.99,
            "prediction_set_size": 4,
        },
    )
    queue.enqueue(
        LIFECYCLE_SWEEP_JOB,
        {
            "states": [
                {
                    "item_id": "postgres-memory-1",
                    "tier": "verbatim",
                    "salience": 0.01,
                    "importance": 0.0,
                    "access_count": 0,
                    "last_accessed": "2020-01-01T00:00:00Z",
                },
                {
                    "item_id": "postgres-memory-2",
                    "tier": "verbatim",
                    "salience": 0.01,
                    "importance": 0.8,
                    "access_count": 1,
                    "last_accessed": "2025-12-01T00:00:00Z",
                    "must_keep": True,
                    "successful_rehearsals": 1,
                    "next_rehearsal_at": "2025-12-31T00:00:00Z",
                }
            ],
            "now": "2026-01-01T00:00:00Z",
        },
    )
    queue.enqueue(EVAL_SUITE_JOB, {"suite": "seed"})
    queue.enqueue(OBSERVABILITY_SNAPSHOT_JOB, {})
    queue.enqueue(
        PROJECTION_RECOMPUTE_JOB,
        {
            "tenant_id": tenant,
            "user_id": user,
            "branch": "main",
            "changed_evidence_cids": [cid],
            "enqueue_consolidation": False,
        },
    )

    drained = worker.drain(limit=5)
    persisted = {job.kind: job for job in queue.list_jobs()}

    assert [job.status for job in drained] == ["complete", "complete", "complete", "complete", "complete"]
    assert queue.snapshot()["complete"] == 5
    assert persisted[CALIBRATE_JOB].result["details"]["abstain"] is True
    assert persisted[LIFECYCLE_SWEEP_JOB].result["details"]["demoted"] == 1
    assert persisted[LIFECYCLE_SWEEP_JOB].result["details"]["rehearsed"] == 1
    assert persisted[LIFECYCLE_SWEEP_JOB].result["details"]["states"][1]["next_rehearsal_at"] == "2026-01-08T00:00:00+00:00"
    assert persisted[EVAL_SUITE_JOB].result["details"]["passed"] is True
    assert persisted[OBSERVABILITY_SNAPSHOT_JOB].result["details"]["metrics"]["counters"]["observability.snapshots"] == 1
    recompute = persisted[PROJECTION_RECOMPUTE_JOB].result["details"]
    assert recompute["affected_projection_counts"]["assertions"] == 1
    assert recompute["affected_projections"]["assertions"] == [assertion_id]
    assert recompute["queued_consolidation_jobs"] == []
    assert engine.export_tenant(tenant)["calibrations"][0]["memory_type"] == "fact"


class StaticMediaExtractor:
    def __init__(self, text: str):
        self.text = text

    def extract(self, payload: bytes, *, media_type: str, modality: str, metadata: dict):
        return MediaExtractionResult(
            text=self.text,
            sources=["test_extractor"],
            metadata={"media_type": media_type, "modality": modality, "bytes": len(payload)},
        )


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


def test_postgres_evidence_vector_search_uses_stored_pgvector_live() -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-evidence-vector-{uuid4()}"
    user = "user-evidence-vector"
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="vector-contract",
            content="Evidence stored pgvector contract uses a durable basalt marker.",
            trust_tier=0,
            sensitivity=0,
            access_policy={"tenant": tenant},
        )
    )

    db_tenant_id = _stable_uuid("tenant", tenant)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)  # noqa: SLF001 - live RLS contract assertion.
            cur.execute(
                """
                SELECT embedding IS NOT NULL
                FROM evidence
                WHERE tenant_id = %s AND branch = 'main' AND cid = %s
                """,
                (db_tenant_id, _cid_to_bytes(cid)),
            )
            assert cur.fetchone()[0] is True

    hits = engine.vector_search(
        "durable basalt stored pgvector",
        5,
        {"tenant_id": tenant, "branch": "main"},
    )
    evidence_hit = next(hit for hit in hits if hit.kind == "evidence" and hit.id == cid)
    assert evidence_hit.channel == "postgres_pgvector"
    assert evidence_hit.metadata["stored_embedding"] is True
    assert evidence_hit.metadata["source_table"] == "evidence"


def test_postgres_evidence_vector_search_keeps_null_embedding_fallback_live() -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-evidence-fallback-{uuid4()}"
    user = "user-evidence-fallback"
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="vector-fallback-contract",
            content="Legacy null embedding fallback keeps the quartz marker searchable.",
            trust_tier=0,
            sensitivity=0,
            access_policy={"tenant": tenant},
        )
    )

    db_tenant_id = _stable_uuid("tenant", tenant)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)  # noqa: SLF001 - live legacy-row simulation.
            cur.execute(
                """
                UPDATE evidence
                SET embedding = NULL
                WHERE tenant_id = %s AND branch = 'main' AND cid = %s
                """,
                (db_tenant_id, _cid_to_bytes(cid)),
            )

    hits = engine.vector_search(
        "quartz legacy fallback",
        5,
        {"tenant_id": tenant, "branch": "main"},
    )
    evidence_hit = next(hit for hit in hits if hit.kind == "evidence" and hit.id == cid)
    assert evidence_hit.channel == "postgres_dense_fallback"
    assert evidence_hit.metadata["stored_embedding"] is False
    assert evidence_hit.metadata["source_table"] == "evidence"


def test_postgres_mcp_runtime_state_persists_profile_and_learning_live() -> None:
    tenant = f"tenant-runtime-state-{uuid4()}"
    user = "user-runtime-state"
    dsn = live_dsn()
    server = MnemosyneMcpServer(backend="postgres", postgres_dsn=dsn, stateless=True, queue_tenant=tenant)

    server.call_tool(
        "profile_add",
        {
            "tenant_id": tenant,
            "user_id": user,
            "kind": "explicit_preference",
            "statement": "Prefer Postgres-backed runtime state for MCP tools.",
            "scope": {"category": "workflow"},
        },
    )
    trajectory = server.call_tool(
        "trajectory_record",
        {
            "tenant_id": tenant,
            "user_id": user,
            "session_id": "session-runtime-state",
            "task": "Postgres runtime state parity",
            "steps": [{"name": "persist", "status": "failed", "error": "runtime state dropped"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v-runtime-state",
        },
    )

    reloaded = MnemosyneMcpServer(backend="postgres", postgres_dsn=dsn, stateless=True, queue_tenant=tenant)
    profile = reloaded.call_tool(
        "profile_context",
        {"tenant_id": tenant, "user_id": user, "scope": {"category": "workflow"}},
    )
    lesson = reloaded.call_tool("lesson_propose", {"trajectory_id": trajectory["id"]})
    procedure = reloaded.call_tool("procedure_propose", {"lesson_id": lesson["id"]})

    assert profile["authoritative"][0]["statement"] == "Prefer Postgres-backed runtime state for MCP tools."
    assert lesson["tenant_id"] == tenant
    assert procedure["tenant_id"] == tenant

    engine = PostgresEngine(dsn)
    db_tenant_id = _stable_uuid("tenant", tenant)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)  # noqa: SLF001 - live RLS mirror assertion.
            cur.execute(
                """
                SELECT
                  (SELECT count(*) FROM runtime_state WHERE tenant_id = %s AND key IN ('user_model', 'learning')),
                  (SELECT count(*) FROM preferences WHERE tenant_id = %s),
                  (SELECT count(*) FROM trajectories WHERE tenant_id = %s),
                  (SELECT count(*) FROM lessons WHERE tenant_id = %s),
                  (SELECT count(*) FROM procedures WHERE tenant_id = %s)
                """,
                (db_tenant_id, db_tenant_id, db_tenant_id, db_tenant_id, db_tenant_id),
            )
            runtime_rows, preferences, trajectories, lessons, procedures = cur.fetchone()

    assert runtime_rows == 2
    assert preferences == 1
    assert trajectories == 1
    assert lessons == 1
    assert procedures == 1


def test_postgres_local_rank_fallback_uses_policy_sensitivity_live() -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-fallback-sensitivity-{uuid4()}"
    user = "user-fallback-sensitivity"
    visible = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="fallback",
            content="Fallback sensitivity contract visible token.",
            trust_tier=0,
            sensitivity=0,
            access_policy={"tenant": tenant},
        )
    )
    hidden = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="fallback",
            content="Fallback sensitivity contract hidden token.",
            trust_tier=0,
            sensitivity=9,
            access_policy={"tenant": tenant},
        )
    )

    default_hits = engine._local_rank(  # noqa: SLF001 - direct regression for fallback filter semantics.
        "fallback sensitivity contract",
        10,
        {"tenant_id": tenant, "branch": "main"},
        channel="fallback-regression",
    )
    override_hits = engine._local_rank(  # noqa: SLF001 - direct regression for fallback filter semantics.
        "fallback sensitivity contract",
        10,
        {"tenant_id": tenant, "branch": "main", "max_sensitivity": 10},
        channel="fallback-regression",
    )

    assert visible in {hit.id for hit in default_hits}
    assert hidden not in {hit.id for hit in default_hits}
    assert hidden in {hit.id for hit in override_hits}


def test_postgres_ingestion_enforces_residency_transfer_policy_live(tmp_path: Path) -> None:
    tenant = f"tenant-residency-live-{uuid4()}"
    user = "user-residency-live"
    dsn = live_dsn()
    required_pipeline = IngestionPipeline(
        PostgresEngine(dsn),
        LocalObjectStore(tmp_path / "required-objects"),
        allowed_residencies=("eu",),
        require_runtime_residency=True,
    )
    with pytest.raises(ValueError, match="runtime residency is required"):
        required_pipeline.ingest(
            IngestRequest(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="postgres-live",
                content="EU live Postgres data needs an explicit processing residency.",
                metadata={"residency": "eu"},
                trust_tier=0,
            )
        )

    denied_pipeline = IngestionPipeline(
        PostgresEngine(dsn),
        LocalObjectStore(tmp_path / "denied-objects"),
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
    )
    with pytest.raises(ValueError, match="cross-region residency transfer"):
        denied_pipeline.ingest(
            IngestRequest(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="postgres-live",
                content="EU live Postgres data cannot process in US without transfer policy.",
                metadata={"residency": "eu"},
                trust_tier=0,
            )
        )

    engine = PostgresEngine(dsn)
    allowed_pipeline = IngestionPipeline(
        engine,
        LocalObjectStore(tmp_path / "allowed-objects"),
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
        allowed_residency_transfers=("eu->us",),
    )
    accepted = allowed_pipeline.ingest(
        IngestRequest(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="postgres-live",
            content="EU live Postgres data can process in US with explicit transfer policy.",
            metadata={"residency": "eu"},
            trust_tier=0,
        )
    )
    exported = engine.export_tenant(tenant)
    evidence = next(item for item in exported["evidence"] if item["cid"] == accepted.cid)

    assert evidence["access_policy"]["runtime_residency"] == "us"
    assert evidence["access_policy"]["cross_region_transfer"] is True
    assert evidence["metadata"]["privacy"]["allowed_residency_transfers"] == ["eu->us"]


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
    run_postgres_cli(
        "branch",
        "--tenant",
        tenant,
        "--name",
        "cli-candidate",
        "--role",
        "operator",
        "--source-trust-tier",
        "0",
    )
    branch_search = run_postgres_cli("search", "--tenant", tenant, "--branch", "cli-candidate", "--query", "CLI backend Postgres")
    run_postgres_cli(
        "discard",
        "--tenant",
        tenant,
        "--branch",
        "cli-candidate",
        "--role",
        "operator",
        "--source-trust-tier",
        "0",
    )
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


def test_postgres_cli_uses_http_retrieval_providers_live() -> None:
    tenant = f"tenant-http-retrieval-live-{uuid4()}"
    user = "user-http-retrieval-live"
    server, base_url, calls = start_fake_retrieval_provider()
    provider_args = (
        "--embedding-provider",
        "http",
        "--embedding-url",
        f"{base_url}/embed",
        "--embedding-model",
        "qwen3-embedding-live",
        "--embedding-api-key",
        "embed-live-token",
        "--reranker-provider",
        "http",
        "--reranker-url",
        f"{base_url}/rerank",
        "--reranker-model",
        "qwen3-reranker-live",
        "--reranker-api-key",
        "rank-live-token",
    )
    try:
        baseline = run_postgres_cli(
            *provider_args,
            "capture",
            "--tenant",
            tenant,
            "--user",
            user,
            "--source-type",
            "http-provider-live",
            "--content",
            "Provider backed retrieval baseline evidence confirms HTTP embeddings reach Postgres.",
            "--trust-tier",
            "0",
        )
        preferred = run_postgres_cli(
            *provider_args,
            "capture",
            "--tenant",
            tenant,
            "--user",
            user,
            "--source-type",
            "http-provider-live",
            "--content",
            "Provider backed retrieval preferred by HTTP reranker confirms adapter parity.",
            "--trust-tier",
            "0",
        )
        search = run_postgres_cli(
            *provider_args,
            "search",
            "--tenant",
            tenant,
            "--query",
            "provider backed retrieval adapter parity",
        )
        explain = run_postgres_cli(
            *provider_args,
            "explain",
            "--tenant",
            tenant,
            "--query",
            "provider backed retrieval adapter parity",
        )
    finally:
        server.shutdown()
        server.server_close()

    db_tenant_id = _stable_uuid("tenant", tenant)
    engine = PostgresEngine(live_dsn())
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)  # noqa: SLF001 - live RLS contract assertion.
            for cid in (baseline["cid"], preferred["cid"]):
                cur.execute(
                    """
                    SELECT embedding IS NOT NULL
                    FROM evidence
                    WHERE tenant_id = %s AND branch = 'main' AND cid = %s
                    """,
                    (db_tenant_id, _cid_to_bytes(cid)),
                )
                assert cur.fetchone()[0] is True

    assert calls["embedding"]
    assert calls["reranker"]
    assert all(call["authorization"] == "Bearer embed-live-token" for call in calls["embedding"])
    assert all(call["authorization"] == "Bearer rank-live-token" for call in calls["reranker"])
    assert any(call["payload"].get("model") == "qwen3-embedding-live" for call in calls["embedding"])
    assert calls["reranker"][-1]["payload"]["model"] == "qwen3-reranker-live"
    assert search["hits"][0]["id"] == preferred["cid"]
    assert "rerank" in search["hits"][0]["channel"]
    assert search["explain"]["channels"]["postgres_dense"] >= 2
    assert search["explain"]["channels"]["postgres_lexical"] >= 1
    assert search["explain"]["adapters"] == {
        "embedding": "http-embedding",
        "embedding_dims": 1024,
        "reranker": "http-reranker",
        "lexical_backend": "postgres-fts",
        "graph_backend": "postgres-recursive-ppr",
    }
    assert explain["explain"]["adapters"]["embedding"] == "http-embedding"
    assert "embed-live-token" not in json.dumps(search)
    assert "rank-live-token" not in json.dumps(explain)


def test_postgres_cli_uses_command_retrieval_adapters_live(tmp_path: Path) -> None:
    tenant = f"tenant-command-retrieval-live-{uuid4()}"
    command, state = fake_command_retrieval_provider(tmp_path)
    provider_args = (
        "--lexical-provider",
        "command",
        "--lexical-command",
        command,
        "--lexical-backend",
        "paradedb-bm25",
        "--graph-provider",
        "command",
        "--graph-command",
        command,
        "--graph-backend",
        "apache-age",
    )

    search = run_postgres_cli(*provider_args, "search", "--tenant", tenant, "--query", "command lexical retrieval")
    deep = run_postgres_cli(*provider_args, "deep-search", "--tenant", tenant, "--query", "command graph retrieval")
    requests = json.loads(state.read_text(encoding="utf-8"))

    assert any(hit["id"] == "lexical-hit-live" for hit in search["hits"])
    assert any(hit["metadata"]["backend"] == "paradedb-bm25" for hit in search["hits"])
    assert any(hit["id"] == "graph-hit-live" for hit in deep["hits"])
    assert any(hit["metadata"]["backend"] == "apache-age" for hit in deep["hits"])
    assert search["explain"]["channels"]["postgres_lexical"] == 1
    assert deep["explain"]["channels"]["postgres_graph_ppr"] == 1
    assert search["explain"]["adapters"]["lexical_backend"] == "paradedb-bm25"
    assert deep["explain"]["adapters"]["graph_backend"] == "apache-age"
    assert [item["role"] for item in requests].count("lexical_search") == 2
    assert [item["role"] for item in requests].count("graph_ppr") == 1
    assert all(item["tenant_id"] == tenant for item in requests)


def test_postgres_cli_http_embedding_provider_fails_closed_live() -> None:
    tenant = f"tenant-bad-http-retrieval-live-{uuid4()}"
    server, base_url, calls = start_fake_retrieval_provider(malformed_embedding=True)
    result: subprocess.CompletedProcess[str]
    try:
        result = run_postgres_cli_raw(
            "--embedding-provider",
            "http",
            "--embedding-url",
            f"{base_url}/embed",
            "capture",
            "--tenant",
            tenant,
            "--user",
            "user-bad-http-retrieval-live",
            "--source-type",
            "bad-http-provider-live",
            "--content",
            "Malformed provider output must not be silently hashed into Postgres.",
            "--trust-tier",
            "0",
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode != 0
    assert "embedding response must contain a non-zero vector" in result.stderr
    assert calls["embedding"]

    db_tenant_id = _stable_uuid("tenant", tenant)
    engine = PostgresEngine(live_dsn())
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)  # noqa: SLF001 - live RLS contract assertion.
            cur.execute(
                """
                SELECT count(*)
                FROM evidence
                WHERE tenant_id = %s AND source_type = 'bad-http-provider-live'
                """,
                (db_tenant_id,),
            )
            assert cur.fetchone()[0] == 0


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


def test_postgres_mcp_stateless_uses_tenant_scoped_durable_queue_live() -> None:
    tenant = f"tenant-mcp-queue-live-{uuid4()}"
    user = "user-mcp-queue-live"
    dsn = live_dsn()
    server = MnemosyneMcpServer(
        backend="postgres",
        postgres_dsn=dsn,
        queue_backend="postgres",
        stateless=True,
    )

    ingested = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": tenant,
                    "user_id": user,
                    "actor": "user",
                    "source_type": "mcp-live",
                    "content": "Stateless Postgres MCP persists durable queue jobs.",
                    "trust_tier": 0,
                },
            },
        }
    )
    queue = PostgresQueue(dsn, tenant_id=tenant)
    other_queue = PostgresQueue(dsn, tenant_id=f"{tenant}-other")
    leased = queue.lease(CONSOLIDATE_EVIDENCE_JOB)

    assert ingested["result"]["isError"] is False
    assert [job["kind"] for job in ingested["result"]["structuredContent"]["queued_jobs"]] == [CONSOLIDATE_EVIDENCE_JOB]
    assert queue.snapshot()["running"] == 1
    assert other_queue.snapshot() == {}
    assert leased is not None
    assert leased.kind == CONSOLIDATE_EVIDENCE_JOB
    assert leased.payload["tenant_id"] == tenant


def test_postgres_cli_ingests_file_with_c2pa_verifier(tmp_path) -> None:
    tenant = f"tenant-cli-c2pa-live-{uuid4()}"
    user = "user-cli-c2pa-live"
    asset = tmp_path / "capture.bin"
    payload = b"postgres binary capture"
    asset.write_bytes(payload)
    asset_hash = sha256(payload).hexdigest()
    verifier_stub = tmp_path / "c2pa-ok.py"
    verifier_stub.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                f"print(json.dumps({{'active_manifest': 'manifest-1', 'claim_generator': 'issuer-a', 'asset_sha256': '{asset_hash}'}}))",
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
    assert ingested["provenance"]["manifest"]["c2pa"]["asset_binding"] == {
        "bound": True,
        "method": "sha256",
        "sha256": asset_hash,
    }
    assert evidence["content_pointer"] == ingested["content_pointer"]
    assert evidence["content"] == "Postgres binary camera capture."
    assert evidence["metadata"]["derived_text_sources"] == ["description"]
    assert evidence["metadata"]["provenance_decision"]["manifest"]["c2pa"]["claim_generator"] == "issuer-a"
    assert "asset-bound-provenance" in evidence["capability_tags"]
    assert search["hits"][0]["id"] == ingested["cid"]


def test_postgres_media_extract_job_appends_searchable_derived_evidence_live(tmp_path) -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-media-live-{uuid4()}"
    user = "user-media-live"
    queue = InProcessQueue()
    object_store = LocalObjectStore(tmp_path / "objects")
    pipeline = IngestionPipeline(engine, object_store, queue=queue)

    result = pipeline.ingest(
        IngestRequest(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="microphone",
            data=b"postgres-audio-bytes",
            modality="audio",
            media_type="audio/wav",
        )
    )
    handlers = RuntimeJobHandlers(
        engine,
        queue,
        object_store=object_store,
        media_extractor=StaticMediaExtractor("Audio transcript says quarterly planning moved."),
    )
    worker = QueueWorker(queue, handlers.handlers())

    assert [job["kind"] for job in result.queued_jobs] == [MEDIA_EXTRACT_JOB, CONSOLIDATE_EVIDENCE_JOB]
    job = worker.run_once(MEDIA_EXTRACT_JOB)
    derived_cid = job.result["details"]["derived_cid"]
    derived_relation_id = job.result["details"]["relation_id"]
    search = engine.retrieve("quarterly planning moved", tenant)
    derived = engine.get_evidence(tenant, derived_cid)
    before_forget = engine.export_tenant(tenant)
    derived_relation = next(item for item in before_forget["relations"] if item["id"] == derived_relation_id)
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            subject="quarterly planning",
            predicate="moved",
            object="true",
            source_evidence_cids=[derived_cid],
            status="active",
            access_policy={"tenant": tenant},
        )
    )
    preference_id = engine.add_preference(
        Preference(
            tenant_id=tenant,
            user_id=user,
            category="workflow",
            statement="Quarterly planning moved.",
            source_evidence_cids=[derived_cid],
        )
    )
    relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="quarterly planning",
            predicate="moved",
            target="true",
            source_evidence_cids=[derived_cid],
            access_policy={"tenant": tenant},
        )
    )
    forgotten = engine.forget(tenant, result.cid)
    exported = engine.export_tenant(tenant)
    exported_assertion = next(item for item in exported["assertions"] if item["id"] == assertion_id)
    exported_preference = next(item for item in exported["preferences"] if item["id"] == preference_id)
    exported_relation = next(item for item in exported["relations"] if item["id"] == relation_id)
    exported_derived_relation = next(item for item in exported["relations"] if item["id"] == derived_relation_id)

    assert job.status == "complete"
    assert derived is not None
    assert derived.metadata["source_evidence_cid"] == result.cid
    assert derived.metadata["derived_text_sources"] == ["test_extractor"]
    assert derived_relation["source"] == result.cid
    assert derived_relation["predicate"] == "media-derived-text"
    assert derived_relation["target"] == derived_cid
    assert derived_relation["source_evidence_cids"] == [result.cid, derived_cid]
    assert search.hits[0].id == derived_cid
    assert forgotten["propagated"]["erased_derived_evidence"] == [derived_cid]
    assert all(item["cid"] not in {result.cid, derived_cid} for item in exported["evidence"])
    assert exported_assertion["status"] == "retracted"
    assert exported_assertion["source_evidence_cids"] == []
    assert exported_preference["status"] == "retracted"
    assert exported_preference["source_evidence_cids"] == []
    assert exported_relation["valid_to"] is not None
    assert exported_relation["source_evidence_cids"] == []
    assert exported_derived_relation["valid_to"] is not None
    assert exported_derived_relation["source_evidence_cids"] == []
    assert forgotten["propagated"]["retracted_preferences"] == [preference_id]
    assert set(forgotten["propagated"]["expired_relations"]) == {relation_id, derived_relation_id}


def test_postgres_cli_ingests_raw_media_embedding_for_vector_retrieval_live(tmp_path) -> None:
    tenant = f"tenant-raw-media-vector-live-{uuid4()}"
    user = "user-raw-media-vector-live"
    media_path = tmp_path / "frame.png"
    media_path.write_bytes(b"\x89PNG opaque raw media vector bytes")
    embedder = tmp_path / "media_embedder.py"
    embedder.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "from mnemosyne.text import hashing_embedding",
                "request = json.load(sys.stdin)",
                "assert request['media_type'] == 'image/png'",
                "assert request['modality'] == 'image'",
                "print(json.dumps({'embedding': hashing_embedding('raw visual memory beacon', dims=1024)}))",
            ]
        ),
        encoding="utf-8",
    )

    ingested = run_postgres_cli(
        "--object-store",
        str(tmp_path / "objects"),
        "--media-embedding-provider",
        "command",
        "--media-embedding-command",
        f"{sys.executable} {embedder}",
        "--media-embedding-dims",
        "1024",
        "ingest",
        "--tenant",
        tenant,
        "--user",
        user,
        "--source-type",
        "camera",
        "--file",
        str(media_path),
        "--modality",
        "image",
        "--media-type",
        "image/png",
        "--trust-tier",
        "0",
        "--no-enqueue-consolidation",
    )
    search = run_postgres_cli(
        "search",
        "--tenant",
        tenant,
        "--query",
        "raw visual memory beacon",
    )

    db_tenant_id = _stable_uuid("tenant", tenant)
    engine = PostgresEngine(live_dsn())
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)  # noqa: SLF001 - live RLS contract assertion.
            cur.execute(
                """
                SELECT content, embedding IS NOT NULL, metadata, capability_tags
                FROM evidence
                WHERE tenant_id = %s AND branch = 'main' AND cid = %s
                """,
                (db_tenant_id, _cid_to_bytes(ingested["cid"])),
            )
            content, has_embedding, metadata, capability_tags = cur.fetchone()

    assert ingested["content_pointer"].startswith("local-object://sha256/")
    assert content == ""
    assert has_embedding is True
    assert metadata["media_embedding"] == {
        "provider": "command-media-embedding",
        "dims": 1024,
        "source": "raw-externalized-media",
    }
    assert "raw-media-embedding-indexed" in capability_tags
    assert search["hits"][0]["id"] == ingested["cid"]
    assert search["hits"][0]["metadata"]["stored_media_embedding"] is True
    assert search["hits"][0]["metadata"]["media_embedding"]["provider"] == "command-media-embedding"


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
    exported_entities = engine.export_tenant(tenant)["entities"]
    assert exported_entities[0]["canonical"] == "postgres-gate-fact"
    assert exported_entities[0]["source_evidence_cids"] == [result.cid]


def test_postgres_gated_consolidation_uses_command_providers_live(tmp_path) -> None:
    engine = PostgresEngine(live_dsn())
    tenant = f"tenant-command-consolidation-live-{uuid4()}"
    user = "user-command-consolidation-live"
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    result = pipeline.ingest(
        IngestRequest(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Meeting note: pg target/local CLI; not a deterministic is-fact sentence.",
        )
    )
    extractor_script = tmp_path / "candidate_extractor.py"
    extractor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "request = json.load(sys.stdin)",
                "evidence = request['evidence'][0]",
                "print(json.dumps({'candidates': [{'signature': 'postgres command target local cli', 'query': 'postgres command target', 'candidate_subject': 'Postgres command target', 'candidate_predicate': 'is', 'candidate_object': 'local CLI', 'confidence': 0.93, 'access_policy': evidence['access_policy']}], 'metadata': {'source': 'live-test-extractor'}}))",
            ]
        ),
        encoding="utf-8",
    )
    summarizer_script = tmp_path / "summarizer.py"
    summarizer_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "json.load(sys.stdin)",
                "print(json.dumps({'summary': 'Postgres command provider summary', 'metadata': {'source': 'live-test-summarizer'}}))",
            ]
        ),
        encoding="utf-8",
    )
    resolver_script = tmp_path / "entity_resolver.py"
    resolver_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "request = json.load(sys.stdin)",
                "candidate = request['candidates'][0]",
                "signature = candidate['signature']",
                "print(json.dumps({'candidates': [{'signature': signature, 'entity_key': 'live-resolved-postgres-command-target'}], 'entities': [{'key': 'live-resolved-postgres-command-target', 'label': 'Live resolved Postgres command target', 'aliases': [candidate['candidate_subject']], 'candidate_signatures': [signature]}]}))",
            ]
        ),
        encoding="utf-8",
    )
    worker = QueueWorker(
        queue,
        {
            CONSOLIDATE_EVIDENCE_JOB: ConsolidationWorker(
                engine,
                gate_cases=[
                    RegressionCase(
                        "postgres-command-provider-smoke",
                        "postgres command target local cli",
                        "postgres command target",
                        "local CLI",
                        protected=True,
                    )
                ],
                candidate_extractor=CommandCandidateExtractor([sys.executable, str(extractor_script)]),
                entity_resolver=CommandEntityResolver([sys.executable, str(resolver_script)]),
                summarizer=CommandEvidenceSummarizer([sys.executable, str(summarizer_script)]),
            ).run_queue_payload
        },
    )

    job = worker.run_once(CONSOLIDATE_EVIDENCE_JOB)
    assert job is not None
    exported = engine.export_tenant(tenant)
    extractor_result = job.result["pass_results"][1]
    resolver_result = next(item for item in job.result["pass_results"] if item["name"] == "resolver")
    summarizer_result = next(item for item in job.result["pass_results"] if item["name"] == "summarizer")
    role_pipeline = job.result["role_pipeline"]
    roles_by_pass = {item["pass"]: item for item in role_pipeline["roles"]}

    assert job.status == "complete"
    assert job.result["candidate_results"][0]["promoted"] is True
    assert role_pipeline["model_backed_roles"] == ["candidate_extractor", "entity_resolver", "evidence_summarizer"]
    assert roles_by_pass["extractor"]["provider"] == "command_candidate_extractor"
    assert roles_by_pass["resolver"]["provider"] == "command_entity_resolver"
    assert roles_by_pass["summarizer"]["provider"] == "command_evidence_summarizer"
    assert extractor_result["details"]["strategy"] == "command_candidate_extractor"
    assert extractor_result["details"]["metadata"] == {"source": "live-test-extractor"}
    assert resolver_result["details"]["strategy"] == "command_entity_resolver"
    assert resolver_result["details"]["resolved_entities"] == [
        {
            "key": "live-resolved-postgres-command-target",
            "label": "Live resolved Postgres command target",
            "aliases": ["Postgres command target"],
            "candidate_signatures": ["postgres command target local cli"],
        }
    ]
    assert summarizer_result["details"]["strategy"] == "command_evidence_summarizer"
    assert summarizer_result["details"]["summary"] == "Postgres command provider summary"
    assert summarizer_result["details"]["materialized"] is True
    summary_evidence = next(item for item in exported["evidence"] if item["source_type"] == "consolidation-summary")
    summary_relation = next(item for item in exported["relations"] if item["predicate"] == "summary-derived-gist")
    assert summary_evidence["cid"] == summarizer_result["details"]["summary_cid"]
    assert summary_evidence["metadata"]["summary"]["strategy"] == "command_evidence_summarizer"
    assert summary_evidence["metadata"]["summary"]["source_evidence_cids"] == [result.cid]
    assert summary_relation["source"] == result.cid
    assert summary_relation["target"] == summary_evidence["cid"]
    assert exported["assertions"][0]["subject"] == "Postgres command target"
    assert exported["assertions"][0]["object"] == "local CLI"
    assert exported["entities"][0]["canonical"] == "live-resolved-postgres-command-target"
