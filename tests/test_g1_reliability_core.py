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


def test_g1_reality_monitoring_accepts_evidence_grounded_alias() -> None:
    engine = LocalMemoryEngine()
    cid = _append(
        engine,
        "Operator source evidence grounds release codename beta.",
        metadata={"reality_class": "evidence_grounded"},
    )

    result = engine.retrieve("release codename beta", TENANT)

    assert LocalMemoryEngine._normalise_reality_class("evidence-grounded") == "grounded"
    assert PostgresEngine._normalise_reality_class("evidence-grounded") == "grounded"
    assert result.hits[0].id == cid
    assert result.explain["reality_monitoring"]["classes"]["grounded"] >= 1
    assert result.explain["reality_monitoring"]["ungrounded_only"] is False
    assert result.explain["reality_monitoring"]["shadow_only"] is False
    assert result.explain["reality_monitoring"]["critical_path"] is True
    assert result.explain["reality_monitoring"]["abstention_gate"]["critical_path"] is True
    assert result.explain["reality_monitoring"]["shadow_tags_shadow_only"] is True
    assert result.explain["reality_monitoring"]["shadow_tags_critical_path"] is False
    shadow_tag = result.explain["reality_monitoring"]["shadow_tags"][cid]
    assert shadow_tag["reality_class"] == "evidence_grounded"
    assert shadow_tag["calibrated"] is True
    assert shadow_tag["confidence"] > 0.8
    postgres_report = PostgresEngine(
        "postgresql://example.invalid/mnemosyne",
    )._reality_monitoring_report(result.hits)
    assert postgres_report["shadow_tags"][cid]["reality_class"] == "evidence_grounded"
    assert postgres_report["critical_path"] is True
    assert postgres_report["shadow_tags_critical_path"] is False


def test_g1_reality_monitoring_rejects_forged_grounded_label() -> None:
    forged = Evidence(
        tenant_id=TENANT,
        user_id=USER,
        actor="external",
        source_type="web-suggestion",
        content="Externally suggested content must not self-attest as grounded.",
        metadata={"reality_class": "evidence_grounded"},
        trust_tier=2,
        access_policy={"tenant": TENANT},
    )

    assert LocalMemoryEngine._classify_evidence_reality(forged) == "unknown"
    assert PostgresEngine._classify_evidence_reality(forged) == "unknown"


def test_g1_projection_reality_monitoring_abstains_on_self_generated_assertion() -> None:
    engine = LocalMemoryEngine()
    cid = _append(
        engine,
        "Synthetic planning scratchpad support for an imagined projection.",
        metadata={"reality_class": "self_generated"},
        actor="system",
    )
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="projection codename",
            predicate="is",
            object="Mirage",
            source_evidence_cids=[cid],
            confidence=0.95,
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )

    result = engine.retrieve("projection codename Mirage", TENANT)
    assertion_hit = next(hit for hit in result.hits if hit.id == assertion_id)
    row = next(item for item in engine.export_tenant(TENANT)["assertions"] if item["id"] == assertion_id)

    assert row["calibration"]["reality_monitoring"]["reality_class"] == "self_generated"
    assert assertion_hit.metadata["reality_class"] == "self_generated"
    assert assertion_hit.metadata["reality_monitoring"]["source"] == "g1_projection_reality_monitoring"
    assert result.abstained is True
    assert result.explain["reality_monitoring"]["ungrounded_only"] is True


def test_g1_projection_reality_monitoring_treats_mixed_support_as_grounded() -> None:
    engine = LocalMemoryEngine()
    generated = _append(
        engine,
        "Synthetic workspace draft mentions a mixed-support projection.",
        metadata={"reality_class": "self_generated"},
        actor="system",
    )
    grounded = _append(
        engine,
        "User supplied source confirms the mixed-support projection.",
        metadata={"reality_class": "grounded"},
    )
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="mixed support projection",
            predicate="is",
            object="confirmed",
            source_evidence_cids=[generated, grounded],
            confidence=0.95,
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )

    result = engine.retrieve("mixed support projection confirmed", TENANT)
    assertion_hit = next(hit for hit in result.hits if hit.id == assertion_id)
    monitoring = assertion_hit.metadata["reality_monitoring"]

    assert monitoring["reality_class"] == "grounded"
    assert monitoring["mixed"] is True
    assert monitoring["classes"]["grounded"] == 1
    assert monitoring["classes"]["self_generated"] == 1
    assert result.explain["reality_monitoring"]["ungrounded_only"] is False


def test_g1_legacy_projection_reality_monitoring_abstains_on_unknown_assertion() -> None:
    engine = LocalMemoryEngine()
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="legacy projection",
            predicate="is",
            object="Unclassified",
            source_evidence_cids=[],
            confidence=0.91,
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    assertion_key = next(key for key, value in engine.assertions.items() if value.id == assertion_id)
    engine.assertions[assertion_key].calibration = {}

    result = engine.retrieve("legacy projection Unclassified", TENANT)
    assertion_hit = next(hit for hit in result.hits if hit.id == assertion_id)

    assert assertion_hit.metadata["reality_class"] == "unknown"
    assert result.abstained is True
    assert result.explain["reality_monitoring"]["classes"]["unknown"] >= 1
    assert assertion_id in result.explain["reality_monitoring"]["risky_hit_ids"]
    assert result.explain["reality_monitoring"]["ungrounded_only"] is True


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


def test_g1_retrieval_strengthening_feeds_forgetter_retention() -> None:
    engine = LocalMemoryEngine()
    cid = _append(
        engine,
        "Retrieval strengthened demotion guard should stay verbatim.",
        metadata={
            "lifecycle": {
                "tier": "verbatim",
                "salience": 0.1,
                "importance": 0.0,
                "access_count": 0,
                "last_accessed": "2025-01-01T00:00:00+00:00",
            }
        },
    )

    result = engine.retrieve("Retrieval strengthened demotion guard", TENANT)
    ev = engine.get_evidence(TENANT, cid)
    assert ev is not None
    refreshed_at = ev.metadata["lifecycle"]["last_accessed"]
    worker = ConsolidationWorker(engine, [], consolidation_min_steps=0)

    sweep = worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "branch": "main",
            "source_evidence_cids": [cid],
            "passes": ["forgetter"],
            "now": refreshed_at,
            "utility_threshold": 0.18,
        }
    )
    forgetter = next(item for item in sweep.pass_results if item["name"] == "forgetter")
    state = forgetter["details"]["states"][0]

    assert result.explain["read_marks"]["evidence"] >= 1
    assert state["from_tier"] == "verbatim"
    assert state["to_tier"] == "verbatim"
    assert state["demoted"] is False


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


def test_g1_schema_fast_path_rejects_self_generated_echo_corroboration() -> None:
    engine = LocalMemoryEngine()
    first = _append(
        engine,
        "Workspace reflection repeats a schema-shaped claim.",
        metadata={"reality_class": "self_generated"},
        actor="system",
    )
    second = _append(
        engine,
        "Another workspace reflection repeats the same schema-shaped claim.",
        metadata={"reality_class": "self_generated"},
        actor="system",
    )

    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="echo schema claim",
            predicate="is",
            object="unsupported",
            source_evidence_cids=[first, second],
            status="candidate",
            scope={"schema_congruent": True},
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    row = next(item for item in engine.export_tenant(TENANT)["assertions"] if item["id"] == assertion_id)
    schema_fast_path = row["calibration"]["schema_fast_path"]

    assert row["status"] == "contested"
    assert schema_fast_path["corroboration_count"] == 0
    assert schema_fast_path["raw_source_count"] == 2
    assert schema_fast_path["rejected_corroboration_count"] == 2
    assert {item["reason"] for item in schema_fast_path["rejected_corroborators"]} == {
        "not_grounded:self_generated"
    }


def test_g1_queue_leases_highest_write_priority_first() -> None:
    queue = InProcessQueue()
    low = queue.enqueue("consolidate", {"write_priority": {"score": 0.1}})
    high = queue.enqueue("consolidate", {"write_priority": {"score": 0.9}})

    first = queue.lease("consolidate")
    second = queue.lease("consolidate")

    assert first is not None and first.id == high.id
    assert second is not None and second.id == low.id


def test_g1_queue_uses_debiased_effective_write_priority() -> None:
    queue = InProcessQueue()
    raw_only = queue.enqueue("consolidate", {"write_priority": {"score": 0.04}})
    debiased = queue.enqueue("consolidate", {"write_priority": {"score": 0.01, "effective_score": 0.05}})

    first = queue.lease("consolidate")
    second = queue.lease("consolidate")

    assert first is not None and first.id == debiased.id
    assert second is not None and second.id == raw_only.id


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
    assert ev.metadata["write_priority"]["effective_score"] >= ev.metadata["write_priority"]["score"]
    assert ev.metadata["write_priority"]["debias"]["source"] == "g1_importance_sampling_debias"
    assert ev.metadata["consolidation"]["prediction_error_gate"] in {
        "promote_to_consolidation",
        "low_prediction_error_metadata_only",
    }
    assert job is not None
    assert job.payload["write_priority"]["score"] == ev.metadata["write_priority"]["score"]
    assert job.payload["prediction_error"]["score"] == ev.metadata["consolidation"]["prediction_error"]


def test_g1_write_priority_debias_floor_is_trust_bounded() -> None:
    engine = LocalMemoryEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)

    result = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Low signal but trusted evidence should retain a small sampling floor.",
            metadata={"importance": 0.0, "novelty": 0.0, "surprise": 0.0, "reward": 0.0},
        )
    )
    ev = engine.get_evidence(TENANT, result.cid)

    assert ev is not None
    assert ev.metadata["write_priority"]["score"] == 0.0
    assert ev.metadata["write_priority"]["effective_score"] == 0.05
    assert ev.metadata["write_priority"]["debias"]["applied"] is True
    assert ev.metadata["write_priority"]["debias"]["sampling_probability"] == 0.05
    assert ev.metadata["write_priority"]["debias"]["importance_weight"] == 20.0


def test_g1_importance_sampling_debias_weights_long_tail_writes() -> None:
    engine = LocalMemoryEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)

    low = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Low priority trusted write gets correction weight.",
            metadata={"importance": 0.0, "novelty": 0.0, "surprise": 0.0, "reward": 0.0},
        )
    )
    high = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="High priority trusted write keeps a small correction weight.",
            metadata={"importance": 1.0, "novelty": 1.0, "surprise": 1.0, "reward": 1.0},
        )
    )
    low_ev = engine.get_evidence(TENANT, low.cid)
    high_ev = engine.get_evidence(TENANT, high.cid)

    assert low_ev is not None
    assert high_ev is not None
    low_debias = low_ev.metadata["write_priority"]["debias"]
    high_debias = high_ev.metadata["write_priority"]["debias"]
    assert low_debias["importance_weight"] > high_debias["importance_weight"]
    assert high_debias["importance_weight"] == 1.0


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
