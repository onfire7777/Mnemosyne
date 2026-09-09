"""G0 deterministic regression cell for surprise-gated write authority.

This synthetic development helper checks only whether the existing ingestion and
consolidation rails classify a write as eligible for core mutation.  It is not
a benchmark, promotion receipt, or evidence of model quality.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.queue import InProcessQueue


class _UnavailablePredictionEngine(LocalMemoryEngine):
    """Deterministically exercise the unmeasured-prediction failure path."""

    def retrieve(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("prediction lookup unavailable")


def _run_case(
    *,
    case_id: str,
    actor: str,
    source_type: str,
    metadata: dict[str, object],
    prediction_available: bool = True,
    expected_core_mutation_eligible: bool,
) -> dict[str, Any]:
    engine = LocalMemoryEngine() if prediction_available else _UnavailablePredictionEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    ingested = pipeline.ingest(
        IngestRequest(
            tenant_id="g0-write-gating",
            user_id="g0-write-gating-user",
            actor=actor,
            source_type=source_type,
            content=f"Synthetic write-gating regression case: {case_id}.",
            metadata=metadata,
        )
    )
    job = queue.lease("consolidate_evidence")
    if job is None:
        raise RuntimeError("ingestion did not enqueue consolidation")
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload(job.payload)
    skipped = set(result.skipped)
    actual_core_mutation_eligible = (
        job.payload["prediction_error"]["gate"] == "promote_to_consolidation"
        and "source_marked_data_only" not in skipped
        and "low_prediction_error_metadata_only" not in skipped
    )
    return {
        "case_id": case_id,
        "expected_core_mutation_eligible": expected_core_mutation_eligible,
        "actual_core_mutation_eligible": actual_core_mutation_eligible,
        "passed": actual_core_mutation_eligible == expected_core_mutation_eligible,
        "prediction_error": dict(job.payload["prediction_error"]),
        "write_priority": dict(job.payload["write_priority"]),
        "skipped": sorted(skipped),
        "source_evidence_cid": ingested.cid,
    }


def run_write_gating_eval() -> dict[str, Any]:
    """Run fixed synthetic cases and return confusion counts without labels in ingestion."""

    rows = [
        _run_case(
            case_id="trusted-high-surprise",
            actor="user",
            source_type="chat",
            metadata={"surprise": 1.0, "importance": 1.0, "novelty": 1.0},
            expected_core_mutation_eligible=True,
        ),
        _run_case(
            case_id="untrusted-high-surprise",
            actor="external",
            source_type="webhook",
            metadata={"surprise": 1.0, "importance": 1.0, "novelty": 1.0},
            expected_core_mutation_eligible=False,
        ),
        _run_case(
            case_id="unmeasured-prediction",
            actor="user",
            source_type="chat",
            metadata={},
            prediction_available=False,
            expected_core_mutation_eligible=False,
        ),
    ]
    confusion_counts = {
        "true_positive": sum(
            row["expected_core_mutation_eligible"] and row["actual_core_mutation_eligible"]
            for row in rows
        ),
        "false_positive": sum(
            not row["expected_core_mutation_eligible"] and row["actual_core_mutation_eligible"]
            for row in rows
        ),
        "true_negative": sum(
            not row["expected_core_mutation_eligible"] and not row["actual_core_mutation_eligible"]
            for row in rows
        ),
        "false_negative": sum(
            row["expected_core_mutation_eligible"] and not row["actual_core_mutation_eligible"]
            for row in rows
        ),
    }
    passed_cases = sum(bool(row["passed"]) for row in rows)
    return {
        "schema_version": "g0.write-gating.v1",
        "metric": "synthetic_write_gating_regression",
        "metric_note": (
            "Deterministic development regression only; it neither evaluates model "
            "quality nor authorizes promotion, publication, or a benchmark claim."
        ),
        "total_cases": len(rows),
        "passed_cases": passed_cases,
        "passed": passed_cases == len(rows),
        "confusion_counts": confusion_counts,
        "rows": rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 write-gating regression")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    report = run_write_gating_eval()
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
