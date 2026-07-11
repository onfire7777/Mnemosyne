from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from eval.datasets.v2.run_grounded_qa_v2 import (
    _PREFLIGHT_SCHEMA,
    _SCALE_DATASET,
    _SCALE_SHA256,
    _validated_preflight,
    compare_retrieval_baseline,
    evaluate,
    load_dataset,
)
from eval.datasets.v2 import run_grounded_qa_v2 as runner


def _dataset() -> dict[str, Any]:
    return {
        "dataset_id": "qa_synthetic_dev_v1",
        "tenant": "dev",
        "user": "dev-user",
        "corpus": [
            {"doc_id": "d1", "content": "Mara owns Helios.", "trust_tier": 0},
            {"doc_id": "d2", "content": "Helios ships in Q3 2026.", "trust_tier": 0},
        ],
        "queries": [
            {
                "qid": "q1",
                "query": "When does Mara's project ship?",
                "gold_answer": "Q3 2026",
                "gold_aliases": ["Q3 2026"],
                "relevant_doc_ids": ["d1", "d2"],
            }
        ],
    }


class RecordingCLI:
    def __init__(self) -> None:
        self.capture_rows: list[dict[str, Any]] = []
        self.answer_rows: list[dict[str, Any]] = []

    def capture_batch(self, path: Path) -> dict[str, Any]:
        self.capture_rows = [json.loads(line) for line in path.read_text().splitlines()]
        return {"results": [{"cid": f"cid-{index}"} for index in range(len(self.capture_rows))]}

    def eval_answer_batch(self, path: Path) -> dict[str, Any]:
        self.answer_rows = [json.loads(line) for line in path.read_text().splitlines()]
        return {
            "results": [
                {
                    "question_id": "q1",
                    "answer": "Q3 2026",
                    "abstained": False,
                    "claims": [{"text": "Q3 2026", "evidence_cids": ["cid-1"]}],
                    "hops": [
                        {"index": 0, "queries": ["Mara"], "channels": ["lexical"], "retrieved_cids": ["cid-0"]},
                        {"index": 1, "queries": ["Helios"], "channels": ["graph"], "retrieved_cids": ["cid-1"]},
                    ],
                    "reader": {"grounded_reader": {}, "query_decomposer": {}},
                }
            ]
        }


def test_synthetic_runner_keeps_gold_at_scorer_boundary() -> None:
    cli = RecordingCLI()
    result = evaluate(_dataset(), cli)  # type: ignore[arg-type]
    assert result["qa"]["metrics"] == {"exact_match": 1.0, "token_f1": 1.0}
    assert result["retrieval"] == {"recall_at_5": 1.0, "ndcg_at_5": 1.0}
    serialized = json.dumps([cli.capture_rows, cli.answer_rows])
    assert all(
        field not in serialized
        for field in ("gold_answer", "gold_aliases", "relevant_doc_ids", "distractor_answer")
    )


def test_frozen_dataset_requires_canonical_path_and_explicit_one_shot_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "frozen.json"
    value = _dataset()
    value["dataset_id"] = "qa_hard_v2"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="frozen"):
        load_dataset(path)
    with pytest.raises(ValueError, match="canonical"):
        load_dataset(path, allow_frozen=True)
    monkeypatch.setattr(runner, "_FROZEN_DATASET", path.resolve())
    assert load_dataset(path, allow_frozen=True)["dataset_id"] == "qa_hard_v2"


def test_no_recall_comparator_reports_exact_regressions() -> None:
    assert compare_retrieval_baseline(
        {"recall_at_5": 1.0, "ndcg_at_5": 1.0},
        {"recall_at_5": 1.0, "ndcg_at_5": 1.0},
    )["passed"] is True
    failed = compare_retrieval_baseline(
        {"recall_at_5": 0.99, "ndcg_at_5": 1.0},
        {"recall_at_5": 1.0, "ndcg_at_5": 1.0},
    )
    assert failed["passed"] is False
    assert failed["regressions"]["recall_at_5"] == {"baseline": 1.0, "measured": 0.99}


def test_frozen_batch_timeout_covers_multi_question_local_inference() -> None:
    assert runner._FROZEN_BATCH_TIMEOUT_SECONDS == 3600


def test_scale_preflight_dataset_and_receipt_are_exactly_bound(tmp_path: Path) -> None:
    assert _SCALE_DATASET.is_file()
    assert hashlib.sha256(_SCALE_DATASET.read_bytes()).hexdigest() == _SCALE_SHA256
    assert len(load_dataset(_SCALE_DATASET)["queries"]) == 24
    receipt = tmp_path / "receipt.json"
    value = {
        "candidate_manifest_sha256": "a" * 64,
        "dataset_sha256": _SCALE_SHA256,
        "metrics": {"exact_match": 1.0, "token_f1": 1.0},
        "result_sha256": "c" * 64,
        "retrieval": {"ndcg_at_5": 1.0, "recall_at_5": 1.0},
        "runtime_manifest_sha256": "b" * 64,
        "schema": _PREFLIGHT_SCHEMA,
        "trace_count": 24,
    }
    receipt.write_text(json.dumps(value))
    validated, digest = _validated_preflight(
        receipt,
        candidate_digest="a" * 64,
        runtime_digest="b" * 64,
    )
    assert validated == value and len(digest) == 64
    value["trace_count"] = 23
    receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="exact gate"):
        _validated_preflight(
            receipt,
            candidate_digest="a" * 64,
            runtime_digest="b" * 64,
        )


def test_attempt_and_result_paths_are_external_exclusive_and_non_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(runner, "_ROOT", repo.resolve())
    external = tmp_path / "external/result.json"
    path = runner._external_new_path(external, "result")
    runner._write_exclusive(path, {"ok": True})
    with pytest.raises(FileExistsError):
        runner._external_new_path(external, "result")
    linked = tmp_path / "linked"
    linked.symlink_to(path)
    with pytest.raises(FileExistsError):
        runner._external_new_path(linked, "result")
    with pytest.raises(ValueError, match="external"):
        runner._external_new_path(repo / "inside.json", "result")
