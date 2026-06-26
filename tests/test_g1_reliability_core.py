from __future__ import annotations

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.models import Assertion, Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.queue import InProcessQueue
from mnemosyne.retrieval import Hit


TENANT = "g1-tenant"
USER = "g1-user"


def _append(engine: LocalMemoryEngine, content: str, *, metadata: dict | None = None, actor: str = "user") -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor=actor,  # type: ignore[arg-type]
            source_type="seed",
            content=content,
            metadata=metadata or {},
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )


def test_g1_schema_fast_path_bridges_multihop_deadline_retrieval() -> None:
    engine = LocalMemoryEngine()
    assignment = _append(engine, "Mara is assigned to project Helios.")
    deadline = _append(engine, "Project Helios has a delivery deadline of Q3 2026.")
    _append(engine, "Project Aurora is budgeted at 90k for the year.")
    _append(engine, "Project Borealis has a delivery deadline of Q2 2026.")

    result = engine.retrieve("what is the delivery deadline of the project Mara is assigned to", TENANT)
    ids = [hit.id for hit in result.hits[:2]]

    assert ids == [assignment, deadline]
    assert result.explain["schema_fast_path"]["applied"] is True
    assert set(result.explain["schema_fast_path"]["boosted_hit_ids"]) >= {assignment, deadline}


def test_g1_schema_fast_path_selects_temporal_as_of_row() -> None:
    engine = LocalMemoryEngine()
    _append(engine, "As of 2024-02-01, the on-call tool vendor was set to PagerDuty.")
    expected = _append(engine, "As of 2025-11-01, the on-call tool vendor was set to Opsgenie.")
    _append(engine, "As of 2026-03-01, the on-call tool vendor was set to Grafana OnCall.")

    result = engine.retrieve("as of 2025-12-15, what was the on-call tool vendor", TENANT)

    assert result.hits[0].id == expected
    assert result.explain["schema_fast_path"]["applied"] is True


def test_g1_reality_monitoring_abstains_on_self_generated_only_support() -> None:
    engine = LocalMemoryEngine()
    cid = _append(
        engine,
        "Imagined release codename alpha is unsupported by source evidence.",
        metadata={"reality_class": "self_generated"},
        actor="system",
    )

    result = engine.retrieve("Imagined release codename alpha", TENANT)

    assert result.hits[0].id == cid
    assert result.abstained is True
    assert result.explain["reality_monitoring"]["ungrounded_only"] is True
    assert result.uncertainty_note is not None
    assert "grounded evidence" in result.uncertainty_note


def test_g1_retrieval_strengthens_evidence_lifecycle_metadata() -> None:
    engine = LocalMemoryEngine()
    cid = _append(engine, "Lifecycle strengthening evidence should survive demotion.", metadata={"lifecycle": {"access_count": 2}})

    result = engine.retrieve("Lifecycle strengthening evidence", TENANT)
    ev = engine.get_evidence(TENANT, cid)

    assert result.explain["read_marks"]["evidence"] >= 1
    assert ev is not None
    assert ev.metadata["lifecycle"]["access_count"] == 3
    assert ev.metadata["lifecycle"]["last_accessed"]
    assert ev.metadata["lifecycle"]["salience"] > 0.5


def test_g1_postgres_read_marks_ignore_provider_local_hit_ids() -> None:
    engine = PostgresEngine("postgresql://unused")
    marks = engine._record_retrieval_access(  # noqa: SLF001 - regression for command adapter ids.
        [
            Hit(
                id="lexical-hit-live",
                kind="evidence",
                tenant_id=TENANT,
                branch="main",
                text="command lexical retrieval reached a provider-local id",
                score=0.91,
                channel="command_lexical",
                metadata={"command_retrieval": True},
            )
        ]
    )

    assert marks == {"assertions": 0, "evidence": 0}


def test_g1_schema_congruent_uncorroborated_projection_is_contested() -> None:
    engine = LocalMemoryEngine()
    cid = _append(engine, "A schema-shaped but single-source claim exists.")

    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="schema claim",
            predicate="is",
            object="single source",
            source_evidence_cids=[cid],
            status="candidate",
            scope={"schema_congruent": True},
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    row = next(item for item in engine.export_tenant(TENANT)["assertions"] if item["id"] == assertion_id)

    assert row["status"] == "contested"
    assert row["calibration"]["schema_fast_path"]["reason"] == "uncorroborated_but_congruent"
    assert row["calibration"]["schema_fast_path"]["min_corroboration"] == 2


def test_g1_queue_leases_highest_write_priority_first() -> None:
    queue = InProcessQueue()
    low = queue.enqueue("consolidate", {"write_priority": {"score": 0.1}})
    high = queue.enqueue("consolidate", {"write_priority": {"score": 0.9}})

    first = queue.lease("consolidate")
    second = queue.lease("consolidate")

    assert first is not None and first.id == high.id
    assert second is not None and second.id == low.id


def test_g1_ingestion_persists_priority_and_prediction_error_metadata() -> None:
    engine = LocalMemoryEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)

    result = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="New surprising evidence should be prioritized for consolidation.",
            metadata={"importance": 0.8, "reward": 0.7},
        )
    )
    ev = engine.get_evidence(TENANT, result.cid)
    job = queue.lease("consolidate_evidence")

    assert ev is not None
    assert ev.metadata["write_priority"]["source"] == "g1_multi_signal_write_priority"
    assert 0.0 <= ev.metadata["write_priority"]["score"] <= 1.0
    assert ev.metadata["consolidation"]["prediction_error_gate"] in {
        "promote_to_consolidation",
        "low_prediction_error_metadata_only",
    }
    assert job is not None
    assert job.payload["write_priority"]["score"] == ev.metadata["write_priority"]["score"]
    assert job.payload["prediction_error"]["score"] == ev.metadata["consolidation"]["prediction_error"]


def test_g1_prediction_error_gate_skips_candidate_extraction_for_low_error() -> None:
    engine = LocalMemoryEngine()
    cid = _append(
        engine,
        "Already explained evidence should not trigger another belief extraction.",
        metadata={"consolidation": {"prediction_error": 0.0}},
    )
    worker = ConsolidationWorker(engine, [], consolidation_min_steps=0)

    result = worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "branch": "main",
            "source_evidence_cids": [cid],
            "passes": ["extractor", "resolver", "belief_reviser", "forgetter"],
            "prediction_error": {"score": 0.0},
        }
    )
    by_pass = {item["name"]: item for item in result.pass_results}

    assert by_pass["prediction_error_gate"]["details"]["gate"] == "low_prediction_error_metadata_only"
    assert by_pass["extractor"]["status"] == "skipped"
    assert "low_prediction_error_metadata_only" in result.skipped
