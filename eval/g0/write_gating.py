"""G0 deterministic regression cell for surprise-gated write authority.

This synthetic development helper reports extraction eligibility and a separate
promotion-safety matrix through the real consolidation gates. It is not a
benchmark, production promotion receipt, or evidence of model quality.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.queue import InProcessQueue
from mnemosyne.models import Assertion, Evidence


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
    prior_support: bool = False,
    expected_core_mutation_eligible: bool,
) -> dict[str, Any]:
    engine = LocalMemoryEngine() if prediction_available else _UnavailablePredictionEngine()
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    if prior_support:
        engine.append_evidence(Evidence(
            tenant_id="g0-write-gating", user_id="g0-write-gating-user",
            actor="user", source_type="note", trust_tier=0,
            content="The preferred database is Postgres.",
            access_policy={"tenant": "g0-write-gating"},
        ))
    ingested = pipeline.ingest(
        IngestRequest(
            tenant_id="g0-write-gating",
            user_id="g0-write-gating-user",
            actor=actor,
            source_type=source_type,
            content="The preferred database is Postgres.",
            metadata=metadata,
        )
    )
    job = queue.lease("consolidate_evidence")
    if job is None:
        raise RuntimeError("ingestion did not enqueue consolidation")
    result = ConsolidationWorker(engine, [], consolidation_min_steps=0).run_queue_payload(job.payload)
    skipped = set(result.skipped)
    extracted_candidates = sum(
        int(row["details"].get("candidate_count", 0))
        for row in result.pass_results
        if row["name"] == "extractor" and row["status"] == "complete"
    )
    actual_core_mutation_eligible = extracted_candidates > 0
    promoted_candidates = sum(row.get("promoted") is True for row in result.candidate_results)
    stored = engine.get_evidence("g0-write-gating", ingested.cid)
    source_preserved = stored is not None and stored.content == "The preferred database is Postgres."
    return {
        "case_id": case_id,
        "extracted_candidates": extracted_candidates,
        "promoted_candidates": promoted_candidates,
        "source_preserved": source_preserved,
        "expected_core_mutation_eligible": expected_core_mutation_eligible,
        "actual_core_mutation_eligible": actual_core_mutation_eligible,
        "passed": actual_core_mutation_eligible == expected_core_mutation_eligible and promoted_candidates == 0 and source_preserved,
        "prediction_error": dict(job.payload["prediction_error"]),
        "write_priority": dict(job.payload["write_priority"]),
        "skipped": sorted(skipped),
        "source_evidence_cid": ingested.cid,
    }


def _promotion_boundary_eval() -> dict[str, Any]:
    """Exercise real promotion decisions; labels remain outside worker inputs."""
    rows = []
    tenant = "g0-promotion-gating"
    for scenario in ["valid", "corroboration", "capability", "protected_check", "mutation_budget", "erasure"]:
        engine = LocalMemoryEngine()
        cids = [engine.append_evidence(Evidence(
            tenant_id=tenant, user_id="user", actor="user", source_type=source,
            content=content, trust_tier=0, access_policy={"tenant": tenant},
        )) for source, content in [
            ("episode", "The preferred database is Postgres."),
            ("chat", "Independent confirmation: preferred database remains Postgres."),
        ][:1 if scenario == "corroboration" else 2]]
        if scenario == "mutation_budget":
            engine.upsert_assertion(Assertion(
                tenant_id=tenant, subject="preferred database", predicate="is",
                object="old-value", trust_tier=2, status="active",
                access_policy={"tenant": tenant},
            ))
        if scenario == "erasure":
            engine.forget(tenant, cids[0], branch="main")
        cases = [RegressionCase(
            id="protected-database", signature="preferred database", query="preferred database",
            expected_substring="SQLite" if scenario == "protected_check" else "Postgres", protected=True,
        )]
        result = ConsolidationWorker(
            engine, cases, consolidation_min_steps=0,
            max_supersession_rate=0.0 if scenario == "mutation_budget" else 0.05,
        ).run_queue_payload({
            "tenant_id": tenant, "source_evidence_cids": cids, "trust_tier": 0,
            "prediction_error": {"score": 1.0}, "surprise": 1.0,
            "signature": "preferred database", "query": "preferred database",
            "candidate_subject": "preferred database", "candidate_predicate": "is",
            "candidate_object": "Postgres",
            "capability_tags": ["no-write-authority"] if scenario == "capability" else [],
            "passes": ["extractor", "resolver", "belief_reviser", "promotion_gate"],
        })
        actual = any(row["promoted"] for row in result.candidate_results)
        failures = [failure for row in result.candidate_results for failure in row["failed_cases"]]
        failure_class = None
        if "source_evidence_unavailable" in result.skipped:
            failure_class = "erasure"
        elif "source_marked_data_only" in result.skipped:
            failure_class = "capability"
        elif any("fact_external_corroboration" in failure for failure in failures):
            failure_class = "corroboration"
        elif "protected-database" in failures:
            failure_class = "protected_check"
        elif any("max_supersession_rate" in failure for failure in failures):
            failure_class = "mutation_budget"
        expected = scenario == "valid"
        source_preserved = all(
            (engine.get_evidence(tenant, cid) is None) == (scenario == "erasure" and index == 0)
            for index, cid in enumerate(cids)
        )
        rows.append({
            "case_id": scenario, "expected_promoted": expected, "actual_promoted": actual,
            "failure_class": failure_class, "source_state_preserved": source_preserved,
            "passed": actual == expected and failure_class == (None if expected else scenario) and source_preserved,
        })
    counts = {
        "true_positive": sum(row["expected_promoted"] and row["actual_promoted"] for row in rows),
        "true_negative": sum(not row["expected_promoted"] and not row["actual_promoted"] for row in rows),
        "false_positive": sum(not row["expected_promoted"] and row["actual_promoted"] for row in rows),
        "false_negative": sum(row["expected_promoted"] and not row["actual_promoted"] for row in rows),
    }
    tp = counts["true_positive"]
    def fraction(denominator: int) -> dict[str, Any]:
        return {"numerator": tp, "denominator": denominator, "value": tp / denominator if denominator else None}
    return {
        "decision_boundary": "candidate_promotion", "total_cases": len(rows),
        "passed_cases": sum(row["passed"] for row in rows), "passed": all(row["passed"] for row in rows),
        "confusion_counts": counts, "precision": fraction(tp + counts["false_positive"]),
        "recall": fraction(tp + counts["false_negative"]), "rows": rows,
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
        _run_case(
            case_id="supported-low-surprise", actor="user", source_type="chat",
            metadata={}, prior_support=True, expected_core_mutation_eligible=False,
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
    promotion_boundary = _promotion_boundary_eval()
    passed_cases = sum(bool(row["passed"]) for row in rows)
    true_positive = confusion_counts["true_positive"]
    precision_denominator = true_positive + confusion_counts["false_positive"]
    recall_denominator = true_positive + confusion_counts["false_negative"]
    return {
        "schema_version": "g0.write-gating.v1",
        "metric": "synthetic_write_gating_regression",
        "metric_note": (
            "Deterministic development regression only; it neither evaluates model "
            "quality nor authorizes promotion, publication, or a benchmark claim."
        ),
        "total_cases": len(rows),
        "passed_cases": passed_cases,
        "passed": passed_cases == len(rows) and promotion_boundary["passed"],
        "promotion_boundary": promotion_boundary,
        "promotion_rails_passed": all(row["promoted_candidates"] == 0 for row in rows),
        "confusion_counts": confusion_counts,
        "decision_boundary": "candidate_extraction",
        "precision": {
            "numerator": true_positive,
            "denominator": precision_denominator,
            "value": true_positive / precision_denominator if precision_denominator else None,
        },
        "recall": {
            "numerator": true_positive,
            "denominator": recall_denominator,
            "value": true_positive / recall_denominator if recall_denominator else None,
        },
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
