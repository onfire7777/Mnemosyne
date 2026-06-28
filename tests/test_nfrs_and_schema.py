from __future__ import annotations

import re
from pathlib import Path

import pytest

from mnemosyne.benchmarks import retrieval_latency_benchmark
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestionPipeline, IngestRequest
from mnemosyne.models import Assertion, Evidence
from mnemosyne.observability import MetricsRegistry
from mnemosyne.privacy import ErasureMode, classify_privacy, redact_pii_text
from mnemosyne.provenance import HowProvenance, how_provenance_for_sources
from mnemosyne.queue import InProcessQueue
from mnemosyne.source_truth import SOURCE_TRUTH_FENCE, parse_markdown_git_blocks
from mnemosyne.storage import LocalObjectStore


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
            trust_tier=0,
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
            trust_tier=0,
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


def test_privacy_classifier_detects_and_redacts_broader_pii() -> None:
    text = (
        "DOB: 1990-04-03, SSN 123-45-6789, card 4111 1111 1111 1111, "
        "passport A1234567, IP 192.168.1.50, address 742 Evergreen St."
    )
    classification = classify_privacy(text)
    redacted = redact_pii_text(text)

    assert set(classification.pii_tags) >= {
        "date-of-birth",
        "ssn",
        "payment-card",
        "passport",
        "ip-address",
        "street-address",
    }
    assert "123-45-6789" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert "192.168.1.50" not in redacted


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
        "runtime_jobs",
        "runtime_state",
    }

    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema


def test_canonical_schema_partitions_sensitive_vector_indexes() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")

    assert "embedding_partition TEXT NOT NULL DEFAULT 'public'" in schema
    assert "CHECK (embedding_partition IN ('public', 'private', 'none'))" in schema
    assert "evidence_embedding_public_hnsw" in schema
    assert "evidence_embedding_private_hnsw" in schema
    assert "assertions_embedding_public_hnsw" in schema
    assert "assertions_embedding_private_hnsw" in schema
    assert "CREATE INDEX IF NOT EXISTS evidence_embedding_hnsw" not in schema
    assert "CREATE INDEX IF NOT EXISTS assertions_embedding_hnsw" not in schema


def test_schema_has_single_preference_valid_to_column() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE IF NOT EXISTS preferences \((.*?)\);", schema, re.S)

    assert match is not None
    assert len(re.findall(r"\bvalid_to\b", match.group(1))) == 1


def test_schema_enables_tenant_row_level_security() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION mnemosyne_current_tenant()" in schema
    for table in [
        "branches",
        "evidence",
        "assertions",
        "relations",
        "preferences",
        "deletion_log",
        "audit_log",
        "runtime_jobs",
        "runtime_state",
    ]:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in schema
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in schema
        assert f"CREATE POLICY {table}_tenant_isolation ON {table}" in schema


def test_compose_file_mounts_schema_for_postgres_parity() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "pgvector/pgvector:pg16" in compose
    assert "./sql/schema.sql:/docker-entrypoint-initdb.d/001-schema.sql:ro" in compose


def test_markdown_git_source_blocks_parse_with_provenance_fields(tmp_path: Path) -> None:
    # Human-authored source-of-truth blocks must parse losslessly with the
    # subject/predicate/object triple and stable git-line provenance identity.
    doc = tmp_path / "notes.md"
    doc.write_text(
        "# Notes\n\n"
        f"```{SOURCE_TRUTH_FENCE}\n"
        'id = "fact-1"\n'
        'subject = "user"\n'
        'predicate = "prefers"\n'
        'object = "concise updates"\n'
        "confidence = 0.9\n"
        "```\n",
        encoding="utf-8",
    )

    blocks = parse_markdown_git_blocks(tmp_path)

    assert len(blocks) == 1
    block = blocks[0]
    assert (block.subject, block.predicate, block.object_value) == (
        "user",
        "prefers",
        "concise updates",
    )
    assert block.confidence == 0.9
    assert block.relative_path == "notes.md"
    assert block.source_identity("abc123") == "git:notes.md@abc123#fact-1"


def test_markdown_git_source_rejects_unclosed_assertion_block(tmp_path: Path) -> None:
    (tmp_path / "broken.md").write_text(
        f"```{SOURCE_TRUTH_FENCE}\nsubject = \"user\"\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unclosed"):
        parse_markdown_git_blocks(tmp_path)


def test_tier0_user_correction_applies_ungated_in_same_turn(tmp_path: Path) -> None:
    # Blueprint §20.7/§30.2: a tier-0 direct-user correction supersedes prior,
    # lower-trust memory immediately in the same turn, without the gated warm loop.
    engine = LocalMemoryEngine()
    pipeline = IngestionPipeline(
        engine,
        object_store=LocalObjectStore(tmp_path / "obj"),
        queue=InProcessQueue(),
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject=USER,
            predicate="manager",
            object="Bob",
            confidence=0.6,
            source_evidence_cids=[],
            status="active",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )

    result = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="No, my manager is Alice now.",
            correction={"subject": USER, "predicate": "manager", "object": "Alice"},
        )
    )

    assert result.correction_applied is True
    assert result.correction_assertion_id is not None

    manager = [a for a in engine.export_tenant(TENANT)["assertions"] if a["predicate"] == "manager"]
    active = [a["object"] for a in manager if a["status"] == "active"]
    assert active == ["Alice"]


def test_non_tier0_actor_correction_is_not_applied_ungated() -> None:
    engine = LocalMemoryEngine()
    pipeline = IngestionPipeline(engine, queue=InProcessQueue())

    result = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="assistant",
            source_type="chat",
            content="Manager is Carol.",
            correction={"subject": USER, "predicate": "manager", "object": "Carol"},
        )
    )

    assert result.correction_applied is False
    assert result.correction_assertion_id is None


def test_how_provenance_semiring_combines_alternatives_and_prunes_erased() -> None:
    # Blueprint I5 (Green/Karvounarakis/Tannen 2007): semiring how-provenance
    # records how sources combine (joint vs alternative) and prunes on erasure.
    a = HowProvenance.source("cidA")
    b = HowProvenance.source("cidB")

    joint = a.combine_and(b)
    alternative = a.combine_or(b)
    assert joint.tag() == "cidA*cidB"
    assert alternative.tag() == "cidA + cidB"
    assert joint.sources() == {"cidA", "cidB"}

    # Semiring identities and positive-Boolean absorption.
    assert HowProvenance.one().combine_and(a) == a
    assert HowProvenance.zero().combine_or(a) == a
    assert a.combine_and(HowProvenance.zero()).is_zero
    assert a.combine_or(joint) == a  # A + A*B = A

    # §27 erasure: a joint derivation dies if any source is erased; an
    # independently corroborated fact survives with the erased source dropped.
    assert joint.prune({"cidA"}).is_zero
    assert alternative.prune({"cidA"}).tag() == "cidB"

    # Builder helper + lossless round-trip.
    assert how_provenance_for_sources(["cidA", "cidB"]).tag() == "cidA*cidB"
    assert how_provenance_for_sources(["cidA", "cidB"], joint=False).tag() == "cidA + cidB"
    assert HowProvenance.from_dict(alternative.to_dict()) == alternative
