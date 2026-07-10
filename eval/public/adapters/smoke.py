"""Development-only smoke adapter."""

from __future__ import annotations

from typing import Any

from eval.harness import metrics
from eval.harness.cli_driver import MnemoCLI


def run(benchmark: dict[str, Any], cli: MnemoCLI) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cid_to_doc: dict[str, str] = {}
    stored = []
    for doc in benchmark["corpus"]:
        result = cli.capture(
            benchmark["tenant"],
            benchmark["user"],
            doc["content"],
            source_type=f"public-smoke:{doc['doc_id']}",
        )
        cid_to_doc[result["cid"]] = doc["doc_id"]
        stored.append(doc["doc_id"])

    traces: list[dict[str, Any]] = []
    successes = 0
    for question in benchmark["questions"]:
        result = cli.search(benchmark["tenant"], question["query"])
        ranked = [cid_to_doc.get(hit["id"], "unmapped") for hit in result.get("hits", [])]
        success = bool(set(ranked[: benchmark["k"]]) & set(question["gold_doc_ids"]))
        successes += int(success)
        traces.append(
            {
                "answer": ranked[0] if ranked else None,
                "gold_references": question["gold_doc_ids"],
                "question_id": question["question_id"],
                "ranked_retrieved_hits": ranked[: benchmark["k"]],
                "scoring_family": "deterministic-retrieval",
                "stored_records": stored,
            }
        )
    interval = metrics.wilson_interval(successes, len(traces)).as_dict()
    return traces, {
        "family": "deterministic-retrieval",
        "interval": {
            "confidence": 0.95,
            "high": interval["ci_high"],
            "low": interval["ci_low"],
            "method": interval["ci_method"],
        },
        "metric": "hit_at_k",
        "successes": successes,
        "total": len(traces),
        "trace_count": len(traces),
        "value": interval["point"],
    }
