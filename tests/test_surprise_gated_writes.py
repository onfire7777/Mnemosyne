"""Phase 15 surprise-gated write safety regressions."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.queue import InProcessQueue


TENANT = "surprise-gated-writes"
USER = "surprise-gated-user"


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


def test_write_gating_regression_reports_reproducible_confusion_counts() -> None:
    """The development cell must expose literal case totals and outcome counts."""

    completed = subprocess.run(
        [sys.executable, "-m", "eval.g0.write_gating", "--print-json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_version"] == "g0.write-gating.v1"
    assert report["total_cases"] == 3
    assert report["passed_cases"] == 3
    assert [row["extracted_candidates"] for row in report["rows"]] == [1, 0, 0]
    assert report["precision"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert report["recall"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert report["decision_boundary"] == "candidate_extraction"
    assert report["confusion_counts"] == {"false_negative": 0, "false_positive": 0, "true_negative": 2, "true_positive": 1}
