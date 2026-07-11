"""Truthful grounded-QA report projection; publication flags stay false."""

from __future__ import annotations

import re
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from eval.datasets.v2.run_grounded_qa_v2 import compare_retrieval_baseline
from eval.public.scoring import score_profile


_SHA = re.compile(r"[0-9a-f]{64}")
_GIT = re.compile(r"[0-9a-f]{40}")


def build_grounded_qa_report(
    *,
    dataset_id: str,
    git_sha: str,
    candidate_manifest_sha256: str,
    qa: Mapping[str, Any],
    retrieval: Mapping[str, float],
    retrieval_baseline: Mapping[str, float],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    if not dataset_id or not _GIT.fullmatch(git_sha) or not _SHA.fullmatch(candidate_manifest_sha256):
        raise ValueError("grounded QA report custody is invalid")
    if qa.get("trace_count") != len(traces) or not traces:
        raise ValueError("grounded QA report trace count mismatch")
    unsupported = 0
    fabricated = 0
    graph = 0
    second_hop = 0
    abstained = 0
    for trace in traces:
        retrieved = {
            cid
            for hop in trace.get("hops", [])
            for cid in hop.get("retrieved_cids", [])
        }
        second_hop += int(len(trace.get("hops", [])) > 1)
        graph += int(
            bool(trace.get("graph_evidence", {}).get("participated"))
            or any(
                channel in {"graph", "ppr"}
                for hop in trace.get("hops", [])
                for channel in hop.get("channels", [])
            )
        )
        abstained += int(trace.get("abstained") is True)
        for claim in trace.get("claims", []):
            citations = claim.get("evidence_cids", [])
            unsupported += int(not citations)
            fabricated += sum(cid not in retrieved for cid in citations)
    return {
        "candidate_git_sha": git_sha,
        "candidate_manifest_sha256": candidate_manifest_sha256,
        "dataset_id": dataset_id,
        "family": "qa",
        "grounding": {
            "abstained": abstained,
            "fabricated_citations": fabricated,
            "graph_participation": graph,
            "second_hop": second_hop,
            "unsupported_claims": unsupported,
        },
        "independent_external_reproduction": False,
        "pbpp_headline_eligible": False,
        "publishable": False,
        "qa": dict(qa),
        "retrieval": dict(retrieval),
        "retrieval_no_regression": compare_retrieval_baseline(retrieval, retrieval_baseline),
        "schema_version": "grounded-qa-report-v1",
    }


def write_grounded_qa_report(path: Path, report: Mapping[str, Any]) -> None:
    repo = Path(__file__).resolve().parents[2]
    path = path.expanduser().resolve()
    if path == repo or repo in path.parents:
        raise ValueError("grounded QA report must be external to the repository")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("grounded QA report path must not contain symlinks")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(json.dumps(report, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def verify_grounded_qa_report(
    report: Mapping[str, Any],
    *,
    labels: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    retrieval_baseline: Mapping[str, float],
) -> dict[str, Any]:
    qa = score_profile("qa-em-f1-v1", labels, traces)
    retrieval_rows = []
    for label, trace in zip(
        sorted(labels, key=lambda row: row["question_id"]),
        sorted(traces, key=lambda row: row["question_id"]),
        strict=True,
    ):
        gold = label.get("gold_references")
        ranked = trace.get("retrieved_doc_ids")
        if not isinstance(gold, list) or not gold or not isinstance(ranked, list):
            raise ValueError("report retrieval labels or traces are incomplete")
        recall = len(set(ranked[:5]) & set(gold)) / len(set(gold))
        dcg = sum(1 / math.log2(index + 2) for index, item in enumerate(ranked[:5]) if item in set(gold))
        ideal = sum(1 / math.log2(index + 2) for index in range(min(5, len(set(gold)))))
        retrieval_rows.append((recall, dcg / ideal))
    retrieval = {
        "recall_at_5": sum(row[0] for row in retrieval_rows) / len(retrieval_rows),
        "ndcg_at_5": sum(row[1] for row in retrieval_rows) / len(retrieval_rows),
    }
    rebuilt = build_grounded_qa_report(
        dataset_id=str(report.get("dataset_id") or ""),
        git_sha=str(report.get("candidate_git_sha") or ""),
        candidate_manifest_sha256=str(report.get("candidate_manifest_sha256") or ""),
        qa=qa,
        retrieval=retrieval,
        retrieval_baseline=retrieval_baseline,
        traces=traces,
    )
    if dict(report) != rebuilt:
        raise ValueError("grounded QA report does not match recomputed evidence")
    return {"valid": True, "dataset_id": report["dataset_id"]}
