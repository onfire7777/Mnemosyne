"""Capture the Phase 12 local-engine dead-graph baseline on development data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from eval.datasets.v2.run_grounded_qa_v2 import _retrieval_score, load_dataset
from eval.harness.cli_driver import MnemoCLI
from mnemosyne.answering import AnswerLimits, _source_bound_anchors
from mnemosyne.providers.extractive_decomposer import (
    ExtractiveQueryDecomposer,
    extract_hop_zero_anchor,
)

_ROOT = Path(__file__).resolve().parents[3]
_DATASET = Path(__file__).with_name("qa_scale_dev_v1.json").resolve()
_MATRIX = Path(__file__).with_name("qa_decomposition_dev_v1.json").resolve()


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    )


def _run_retrieval(dataset: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True)
    store = output / "store.json"
    tenant = dataset["tenant"]
    runtime_rows = [
        {
            "tenant": tenant,
            "user": dataset["user"],
            "source_type": "qa-v2-dev",
            "source_identity": row["doc_id"],
            "content": row["content"],
            "trust_tier": int(row.get("trust_tier", 0)),
        }
        for row in dataset["corpus"]
    ]
    capture_path = output / "capture.jsonl"
    capture_path.write_text(_jsonl(runtime_rows), encoding="utf-8")
    captured = MnemoCLI(store=str(store), timeout_s=3600.0).capture_batch(capture_path)
    capture_results = captured.get("results")
    if not isinstance(capture_results, list) or len(capture_results) != len(runtime_rows):
        raise ValueError("grounded QA capture count mismatch")
    cid_to_doc = {
        result["cid"]: runtime["source_identity"]
        for runtime, result in zip(runtime_rows, capture_results, strict=True)
    }

    query_rows = [
        {"question_id": row["qid"], "tenant": tenant, "query": row["query"]}
        for row in dataset["queries"]
    ]
    query_path = output / "queries.jsonl"
    query_path.write_text(_jsonl(query_rows), encoding="utf-8")
    queried = MnemoCLI(
        store=str(store),
        global_flags=["--evaluation-read-only"],
        timeout_s=3600.0,
    ).eval_query_batch(query_path)
    results = queried.get("results")
    if not isinstance(results, list) or len(results) != len(query_rows):
        raise ValueError("grounded QA query count mismatch")

    traces: list[dict[str, Any]] = []
    scores: list[tuple[float, float]] = []
    disclosed_backends: set[str] = set()
    for question, result in zip(dataset["queries"], results, strict=True):
        search = result["search"]
        explanation = result["explanation"]
        channels = explanation["channels"]
        disclosed_backends.add(explanation["adapters"]["graph_backend"])
        retrieved = list(
            dict.fromkeys(
                cid_to_doc[hit["id"]]
                for hit in search["hits"]
                if hit.get("id") in cid_to_doc
            )
        )
        scores.append(_retrieval_score(retrieved[:5], question["relevant_doc_ids"]))
        traces.append(
            {
                "channels": channels,
                "question_id": question["qid"],
                "retrieved_doc_ids": retrieved,
            }
        )

    trace_bytes = _jsonl(traces).encode()
    (output / "traces.jsonl").write_bytes(trace_bytes)
    state = json.loads(store.read_text(encoding="utf-8"))
    metrics = {
        "actual_engine": "local",
        "disclosed_graph_backends": sorted(disclosed_backends),
        "graph_ppr_channel_sum": sum(row["channels"]["graph_ppr"] for row in traces),
        "ndcg_at_5": sum(score[1] for score in scores) / len(scores),
        "query_count": len(traces),
        "recall_at_5": sum(score[0] for score in scores) / len(scores),
        "relations": len(state.get("relations", [])),
        "trace_sha256": hashlib.sha256(trace_bytes).hexdigest(),
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metrics


def _run_decomposition_matrix() -> dict[str, int]:
    payload = json.loads(_MATRIX.read_text(encoding="utf-8"))
    passed = 0
    for case in payload["cases"]:
        result = extract_hop_zero_anchor(case["question"])
        if result != tuple(case["expected"]):
            raise AssertionError(case["id"])
        if result and _source_bound_anchors(
            list(result), (case["question"],), AnswerLimits()
        ) != result:
            raise AssertionError(f"source-bound anchor drift: {case['id']}")
        passed += 1
    if ExtractiveQueryDecomposer().decompose(
        {
            "question": "When does project cobalt launch?",
            "evidence": [{"cid": "c1", "content": "project cobalt belongs to team juniper"}],
        }
    ) != {"queries": []}:
        raise AssertionError("authorized-evidence deferral drift")
    return {"case_count": passed + 1, "passed": passed + 1}


def run_baseline(output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("baseline output must not already exist")
    dataset = load_dataset(_DATASET)
    first = _run_retrieval(dataset, output / "run-1")
    second = _run_retrieval(dataset, output / "run-2")
    summary = {
        "dataset_id": dataset["dataset_id"],
        "decomposition_matrix": _run_decomposition_matrix(),
        "runs": [first, second],
        "traces_byte_identical": (output / "run-1/traces.jsonl").read_bytes()
        == (output / "run-2/traces.jsonl").read_bytes(),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run_baseline(args.output.expanduser().resolve())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
