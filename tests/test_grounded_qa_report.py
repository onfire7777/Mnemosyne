from __future__ import annotations

import pytest

from eval.public.qa_report import (
    build_grounded_qa_report,
    verify_grounded_qa_report,
    write_grounded_qa_report,
)
from eval.public.scoring import score_profile


def test_grounded_qa_report_binds_custody_rails_and_no_regression() -> None:
    traces = [{
        "abstained": False,
        "answer": "answer",
        "claims": [{"text": "answer", "evidence_cids": ["cid-1"]}],
        "hops": [
            {"retrieved_cids": ["cid-0"]},
            {"retrieved_cids": ["cid-1"]},
        ],
        "graph_evidence": {"participated": True},
        "question_id": "q1",
        "retrieved_doc_ids": ["d1"],
        "scoring_family": "qa",
    }]
    labels = [{"answers": ["answer"], "gold_references": ["d1"], "question_id": "q1"}]
    qa = score_profile("qa-em-f1-v1", labels, traces)
    report = build_grounded_qa_report(
        dataset_id="synthetic-dev",
        git_sha="a" * 40,
        candidate_manifest_sha256="b" * 64,
        qa=qa,
        retrieval={"recall_at_5": 1.0, "ndcg_at_5": 1.0},
        retrieval_baseline={"recall_at_5": 1.0, "ndcg_at_5": 1.0},
        traces=traces,
    )
    assert report["grounding"] == {
        "abstained": 0,
        "fabricated_citations": 0,
        "graph_participation": 1,
        "second_hop": 1,
        "unsupported_claims": 0,
    }
    assert report["retrieval_no_regression"]["passed"] is True
    assert report["publishable"] is False
    assert report["pbpp_headline_eligible"] is False
    assert report["independent_external_reproduction"] is False
    assert verify_grounded_qa_report(
        report,
        labels=labels,
        traces=traces,
        retrieval_baseline={"recall_at_5": 1.0, "ndcg_at_5": 1.0},
    ) == {"valid": True, "dataset_id": "synthetic-dev"}


def test_grounded_qa_report_writer_is_no_overwrite(tmp_path) -> None:
    path = tmp_path / "report.json"
    write_grounded_qa_report(path, {"schema": "test"})
    with pytest.raises(FileExistsError):
        write_grounded_qa_report(path, {"schema": "changed"})
