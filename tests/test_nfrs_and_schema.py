from __future__ import annotations

import re
from pathlib import Path

from mnemosyne.benchmarks import retrieval_latency_benchmark
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.observability import MetricsRegistry
from mnemosyne.privacy import ErasureMode, classify_privacy


TENANT = "tenant-g"
USER = "user-g"


def seeded_engine() -> LocalMemoryEngine:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="seed",
            content="Fast retrieval should stay below the local benchmark budget.",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            subject="fast retrieval",
            predicate="stays below",
            object="local benchmark budget",
            confidence=0.9,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )
    return engine


def test_fast_retrieval_latency_benchmark_runs_under_blueprint_budget() -> None:
    engine = seeded_engine()
    result = retrieval_latency_benchmark(engine, TENANT, ["fast retrieval", "benchmark budget"] * 5)

    assert result.query_count == 10
    assert result.p95_ms < 300.0


def test_observability_registry_records_required_memory_metrics() -> None:
    registry = MetricsRegistry()
    registry.record_retrieval({"lexical": 2, "dense_hash": 1, "graph_ppr": 0}, latency_ms=12.5, abstained=True)
    registry.record_gate(promoted=True, rolled_back=False)
    snapshot = registry.snapshot()

    assert snapshot.counters["retrieval.channel.lexical.hits"] == 2
    assert snapshot.counters["retrieval.abstentions"] == 1
    assert snapshot.counters["gate.promotions"] == 1
    assert snapshot.gauges["retrieval.p95_ms.latest_sample"] == 12.5


def test_privacy_classifier_tags_pii_and_erasure_mode() -> None:
    normal = classify_privacy("Reach me at user@example.com or 415-555-0100.", residency="us")
    legal = classify_privacy("Legal erasure request for user@example.com", legal_erasure=True)

    assert normal.pii_tags == ["email", "phone"]
    assert normal.residency == "us"
    assert normal.erasure_mode == ErasureMode.TOMBSTONE_RECOMPUTE
    assert legal.erasure_mode == ErasureMode.HARD_DELETE_LEGAL


def test_canonical_schema_includes_all_blueprint_core_tables() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")
    required_tables = {
        "evidence",
        "assertions",
        "justifications",
        "entities",
        "relations",
        "branches",
        "procedures",
        "lessons",
        "preferences",
        "user_latent",
        "trajectories",
        "self_model",
        "eval_cases",
        "audit_log",
        "entity_aliases",
        "contradictions",
        "resources",
        "merges",
        "deletion_log",
        "conformal_calibration",
    }

    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema


def test_schema_has_single_preference_valid_to_column() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE IF NOT EXISTS preferences \((.*?)\);", schema, re.S)

    assert match is not None
    assert len(re.findall(r"\bvalid_to\b", match.group(1))) == 1


def test_compose_file_mounts_schema_for_postgres_parity() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "pgvector/pgvector:pg16" in compose
    assert "./sql/schema.sql:/docker-entrypoint-initdb.d/001-schema.sql:ro" in compose
