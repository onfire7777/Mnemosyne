"""Phase 15 surprise-gated write safety regressions.

From codex/complete-ai-memory-prs (9 Sep 2026), kept beside main's own
test_surprise_gated_writes.py: these cases are not covered there. The branch's
report-schema test was dropped - main's eval/g0/write_gating.py reports the same
confusion counts and denominators in its own shape.
"""

from __future__ import annotations

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.queue import InProcessQueue
from mnemosyne.models import Assertion, Evidence


TENANT = "surprise-gated-writes"
USER = "surprise-gated-user"


@pytest.mark.parametrize("rate, allowed", [(0.0, False), (0.05, True)])
def test_high_surprise_respects_supersession_budget(rate, allowed) -> None:
    """Bypassing the pre-merge budget would replace a fact despite a zero limit."""
    engine = LocalMemoryEngine()
    original_ids = []
    for index in range(20):
        assertion = Assertion(
            tenant_id=TENANT, subject="preferred database" if index == 0 else f"unrelated-{index}",
            predicate="is", object="old-value", confidence=0.7,
            trust_tier=2, status="active", access_policy={"tenant": TENANT},
        )
        engine.upsert_assertion(assertion)
        original_ids.append(assertion.id)
    cids = [engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type=source,
        content=content, trust_tier=0, access_policy={"tenant": TENANT},
    )) for source, content in [
        ("episode", "The preferred database is Postgres."),
        ("chat", "Independent confirmation: preferred database remains Postgres."),
    ]]
    cases = [RegressionCase(
        id="database", signature="preferred database", query="preferred database",
        expected_substring="Postgres", protected=True,
    )]
    result = ConsolidationWorker(
        engine, cases, consolidation_min_steps=0, max_supersession_rate=rate,
    ).run_queue_payload({
        "tenant_id": TENANT, "source_evidence_cids": cids, "trust_tier": 0,
        "prediction_error": {"score": 1.0}, "surprise": 1.0,
        "signature": "preferred database", "query": "preferred database",
        "candidate_subject": "preferred database", "candidate_predicate": "is",
        "candidate_object": "Postgres",
        "passes": ["extractor", "resolver", "belief_reviser", "promotion_gate"],
    })
    assert len(result.candidate_results) == 1
    assert result.candidate_results[0]["promoted"] is allowed
    active_ids = {row.id for row in engine.assertions.values()
                  if row.branch == "main" and row.status in {"active", "contested"}}
    assert len(set(original_ids) - active_ids) == int(allowed)
    rail = next(row["details"] for row in result.pass_results if row["name"] == "mutation_rails")
    assert rail["supersessions_used"] == int(allowed)
    if not allowed:
        assert any(row["rail"] == "max_supersession_rate" for row in rail["violations"])


@pytest.mark.parametrize("tag", [None, "data-only", "no-write-authority", "sanitize-as-data", "quarantined"])
@pytest.mark.parametrize("location", ["payload", "evidence"])
def test_high_surprise_cannot_override_batch_capability_restrictions(tag, location) -> None:
    """Removing either source or payload capability checks must permit a forbidden write."""
    engine = LocalMemoryEngine()
    cids = []
    for index, content in enumerate([
        "The preferred database is Postgres.",
        "Independent confirmation: preferred database remains Postgres.",
    ]):
        cids.append(engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id=USER, actor="user",
            source_type="chat" if index else "episode", content=content,
            trust_tier=0, access_policy={"tenant": TENANT},
            capability_tags=[tag] if tag and location == "evidence" and index == 1 else [],
        )))
    payload = {
        "tenant_id": TENANT, "source_evidence_cids": cids,
        "prediction_error": {"score": 1.0}, "surprise": 1.0,
        "signature": "preferred database", "query": "preferred database",
        "candidate_subject": "preferred database", "candidate_predicate": "is",
        "candidate_object": "Postgres",
        "capability_tags": [tag] if tag and location == "payload" else [],
    }
    cases = [RegressionCase(
        id="preferred-database", signature="preferred database", query="preferred database",
        expected_substring="Postgres", protected=True,
    )]
    result = ConsolidationWorker(engine, cases, consolidation_min_steps=0).run_queue_payload(payload)
    if tag is None:
        assert result.candidate_results
        assert all(row["promoted"] for row in result.candidate_results), result.candidate_results
    else:
        assert "source_marked_data_only" in result.skipped
        assert result.candidate_results == []
    for cid in cids:
        assert engine.get_evidence(TENANT, cid) is not None


def test_erased_source_cannot_reenter_extraction_from_queued_candidate() -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content="The preferred database is Postgres.", trust_tier=0,
        access_policy={"tenant": TENANT},
    ))
    payload = {
        "tenant_id": TENANT, "source_evidence_cids": [cid],
        "prediction_error": {"score": 1.0},
        "signature": "preferred database", "query": "preferred database",
        "candidate_subject": "preferred database", "candidate_predicate": "is",
        "candidate_object": "Postgres",
    }
    engine.forget(TENANT, cid, branch="main")
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload(payload)
    assert result.candidate_results == []
    assert engine.get_evidence(TENANT, cid) is None


@pytest.mark.parametrize("expected_answer, promoted", [("Postgres", True), ("SQLite", False)])
def test_high_surprise_does_not_bypass_failing_protected_case(expected_answer, promoted) -> None:
    """Bypassing the real regression gate would promote the failing SQLite case."""
    engine = LocalMemoryEngine()
    cids = [engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type=source,
        content=content, trust_tier=0, access_policy={"tenant": TENANT},
    )) for source, content in [
        ("episode", "The preferred database is Postgres."),
        ("chat", "Independent confirmation: preferred database remains Postgres."),
    ]]
    cases = [RegressionCase(
        id="protected-database-answer", signature="preferred database",
        query="preferred database", expected_substring=expected_answer, protected=True,
    )]
    result = ConsolidationWorker(engine, cases, consolidation_min_steps=0).run_queue_payload({
        "tenant_id": TENANT, "source_evidence_cids": cids,
        "prediction_error": {"score": 1.0}, "surprise": 1.0,
        "signature": "preferred database", "query": "preferred database",
        "candidate_subject": "preferred database", "candidate_predicate": "is",
        "candidate_object": "Postgres",
    })
    assert len(result.candidate_results) == 1
    decision = result.candidate_results[0]
    assert decision["promoted"] is promoted
    assert decision["failed_cases"] == ([] if promoted else ["protected-database-answer"])
    for cid in cids:
        assert engine.get_evidence(TENANT, cid) is not None


@pytest.mark.parametrize("signal", [None, True, "bad", float("nan"), float("inf"), -1.0, 2.0])
def test_invalid_ingestion_surprise_does_not_boost_queue_priority(signal) -> None:
    engine = LocalMemoryEngine()
    queue = InProcessQueue()
    IngestionPipeline(engine, queue=queue).ingest(IngestRequest(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content="The preferred database is Postgres.", metadata={"surprise": signal},
    ))
    job = queue.lease("consolidate_evidence")
    assert job is not None
    assert job.payload["write_priority"]["components"]["surprise"] == 0.0


@pytest.mark.parametrize("signal", [None, True, "bad", float("nan"), float("inf"), -1.0, 2.0])
def test_invalid_surprise_cannot_increase_replay_priority(signal) -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content="The preferred database is Postgres.", trust_tier=0,
        access_policy={"tenant": TENANT},
    ))
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload({
        "tenant_id": TENANT, "source_evidence_cids": [cid],
        "prediction_error": {"score": 0.0},
        "replay_scores": {cid: {"surprise": signal}},
    })
    replay = next(row for row in result.pass_results if row["name"] == "replayer")
    assert replay["details"]["scores"][0]["surprise"] == 0.0
    assert replay["details"]["scores"][0]["score"] == 0.0


@pytest.mark.parametrize("signal", [None, True, "bad", float("nan"), float("inf"), -1.0, 2.0])
def test_worker_rejects_explicit_invalid_prediction_signal(signal) -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content="The preferred database is Postgres.", trust_tier=0,
        access_policy={"tenant": TENANT},
    ))
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload({
        "tenant_id": TENANT, "source_evidence_cids": [cid],
        "prediction_error": {"score": signal},
    })
    assert "low_prediction_error_metadata_only" in result.skipped
    assert result.candidate_results == []


@pytest.mark.parametrize("support", [None, float("nan"), float("inf"), -float("inf"), -0.1, 1.1, True, "invalid"])
@pytest.mark.parametrize("shape", ["score", "confidence", "query_support"])
def test_invalid_prediction_support_stays_metadata_only(monkeypatch, support, shape) -> None:
    engine = LocalMemoryEngine()
    original_retrieve = engine.retrieve

    def invalid_support(*args, **kwargs):
        result = original_retrieve(*args, **kwargs)
        result.explain["confidence"] = {"query_support": {"score": support}}
        if shape == "confidence":
            result.explain["confidence"] = support
        elif shape == "query_support":
            result.explain["confidence"]["query_support"] = support
        return result

    monkeypatch.setattr(engine, "retrieve", invalid_support)
    queue = InProcessQueue()
    IngestionPipeline(engine, queue=queue).ingest(IngestRequest(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content="Malformed support cannot authorize extraction.",
    ))
    job = queue.lease("consolidate_evidence")
    assert job is not None
    assert job.payload["prediction_error"]["score"] == 0.0
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload(job.payload)
    assert "low_prediction_error_metadata_only" in result.skipped


class _UnavailablePredictionEngine(LocalMemoryEngine):
    """Exercise the real pipeline when its prediction lookup is unavailable."""

    def retrieve(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("prediction lookup unavailable")


@pytest.mark.parametrize("metadata", [{}, {"consolidation": {"prediction_error": 1.0, "prediction_error_gate": "promote_to_consolidation"}}])
def test_unmeasured_prediction_error_cannot_raise_consolidation_authority(metadata: dict) -> None:
    """A failed prediction lookup must remain metadata-only through consolidation."""

    engine = _UnavailablePredictionEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)

    ingested = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="A prediction lookup failure must not make this write surprising.",
            metadata=metadata,
        )
    )
    job = queue.lease("consolidate_evidence")

    assert job is not None
    assert job.payload["prediction_error"]["score"] == 0.0
    assert job.payload["prediction_error"]["gate"] == "unmeasured_fail_closed_metadata_only"

    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload(job.payload)
    by_pass = {row["name"]: row for row in result.pass_results}

    assert by_pass["prediction_error_gate"]["details"]["gate"] == "low_prediction_error_metadata_only"
    assert "low_prediction_error_metadata_only" in result.skipped
    assert ingested.cid in job.payload["source_evidence_cids"]


def test_external_high_surprise_evidence_stays_data_only() -> None:
    """High surprise must not let untrusted external evidence enter core mutation."""

    engine = LocalMemoryEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="external",
            source_type="webhook",
            content="Untrusted external content claims an urgent surprising fact.",
            metadata={"surprise": 1.0, "importance": 1.0, "novelty": 1.0},
        )
    )
    job = queue.lease("consolidate_evidence")

    assert job is not None
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload(job.payload)
    by_pass = {row["name"]: row for row in result.pass_results}

    assert job.payload["prediction_error"]["score"] >= 0.35
    assert by_pass["extractor"]["status"] == "skipped"
    assert by_pass["extractor"]["details"]["reason"] == "source_marked_data_only"
    assert "source_marked_data_only" in result.skipped
