from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from eval.datasets.v2.run_grounded_qa_v2 import (
    _FROZEN_DATASET,
    _FROZEN_SHA256,
    _PREFLIGHT_SCHEMA,
    _SCALE_DATASET,
    _SCALE_SHA256,
    _validated_preflight,
    attach_custody,
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
    """Public-CLI stand-in that records capture/answer payloads without gold."""

    def __init__(self, answers: list[dict[str, Any]] | None = None) -> None:
        self.capture_rows: list[dict[str, Any]] = []
        self.answer_rows: list[dict[str, Any]] = []
        self.consolidated = False
        self._answers = answers

    def capture_batch(
        self, path: Path, *, consolidate: bool = False
    ) -> dict[str, Any]:
        self.consolidated = consolidate
        self.capture_rows = [json.loads(line) for line in path.read_text().splitlines()]
        return {"results": [{"cid": f"cid-{index}"} for index in range(len(self.capture_rows))]}

    def eval_answer_batch(self, path: Path) -> dict[str, Any]:
        self.answer_rows = [json.loads(line) for line in path.read_text().splitlines()]
        if self._answers is not None:
            return {"results": self._answers}
        return {
            "results": [
                {
                    "question_id": "q1",
                    "answer": "Q3 2026",
                    "abstained": False,
                    "claims": [{"text": "Q3 2026", "evidence_cids": ["cid-1"]}],
                    "hops": [
                        {
                            "index": 0,
                            "queries": ["Mara"],
                            "channels": ["lexical"],
                            "retrieved_cids": ["cid-0"],
                        },
                        {
                            "index": 1,
                            "queries": ["Helios"],
                            "channels": ["graph"],
                            "retrieved_cids": ["cid-1"],
                        },
                    ],
                    "reader": {
                        "grounded_reader": {
                            "artifact": "compact-int8.onnx",
                            "provider": "answering-ort",
                            "wire_protocol": "answering-ort",
                        },
                        "query_decomposer": {},
                    },
                }
            ]
        }


def test_synthetic_runner_keeps_gold_at_scorer_boundary() -> None:
    cli = RecordingCLI()
    result = evaluate(_dataset(), cli)  # type: ignore[arg-type]
    assert result["qa"]["metrics"] == {"exact_match": 1.0, "token_f1": 1.0}
    assert result["retrieval"] == {"recall_at_5": 1.0, "ndcg_at_5": 1.0}
    intervals = result["qa"]["intervals"]
    assert intervals["exact_match"]["method"] == "wilson"
    assert intervals["token_f1"]["method"] == "bootstrap"
    assert result["grounding"] == {
        "abstained": 0,
        "fabricated_citations": 0,
        "graph_participation": 1,
        "second_hop": 1,
        "unsupported_claims": 0,
    }
    assert result["trace_count"] == 1
    assert result["traces"][0]["scoring_family"] == "qa"
    assert "reader" in result["traces"][0]
    serialized = json.dumps([cli.capture_rows, cli.answer_rows])
    assert cli.consolidated is True
    assert all(
        field not in serialized
        for field in ("gold_answer", "gold_aliases", "relevant_doc_ids", "distractor_answer")
    )
    assert cli.answer_rows == [{
        "context": {"role": "reader", "tenant_id": "dev", "user_id": "dev-user"},
        "question": "When does Mara's project ship?",
        "question_id": "q1",
    }]
    assert result["traces"][0]["reader"]["grounded_reader"] == {
        "artifact": "compact-int8.onnx",
        "provider": "answering-ort",
        "wire_protocol": "answering-ort",
    }
    for row in cli.capture_rows + cli.answer_rows:
        assert not runner._GOLD_FIELDS & set(row)


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


def test_phase12_v19_custody_constants_bind_external_freeze() -> None:
    freeze = runner.PHASE12_V19_FREEZE
    assert freeze["candidate_version"] == "phase12-candidate-v19"
    assert freeze["git_sha"] == "df438ca34061467ecc227bcf4d45bb1f7e886aee"
    assert freeze["manifest_sha256"] == (
        "e81fc655f81ab43f1cfd5ad1b8644a9271a190027c49233efe89a2dd682c95f3"
    )
    path = Path(freeze["path"])
    if not path.exists():
        # The freeze manifest is external no-overwrite evidence (deliberately
        # out-of-repo), so it cannot exist on CI runners. The constants above
        # stay pinned unconditionally; the evaluator still fail-closes at
        # runtime via validate_candidate_manifest before any frozen execution.
        pytest.skip("external phase12-v19 freeze artifact absent in this workspace")
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == freeze["manifest_sha256"]
    manifest = json.loads(raw)
    assert manifest["git_sha"] == freeze["git_sha"]
    assert manifest["candidate_version"] == freeze["candidate_version"]


def test_attach_custody_projects_digest_and_git_sha() -> None:
    base = {
        "dataset_id": "qa_synthetic_dev_v1",
        "qa": {"metrics": {"exact_match": 1.0, "token_f1": 1.0}},
        "retrieval": {"recall_at_5": 1.0, "ndcg_at_5": 1.0},
        "grounding": {
            "abstained": 0,
            "fabricated_citations": 0,
            "graph_participation": 1,
            "second_hop": 1,
            "unsupported_claims": 0,
        },
        "trace_count": 1,
        "traces": [],
    }
    projected = attach_custody(
        base,
        git_sha="df438ca34061467ecc227bcf4d45bb1f7e886aee",
        candidate_manifest_sha256="e81fc655f81ab43f1cfd5ad1b8644a9271a190027c49233efe89a2dd682c95f3",
        candidate_version="phase12-candidate-v19",
    )
    assert projected["candidate_git_sha"] == "df438ca34061467ecc227bcf4d45bb1f7e886aee"
    assert projected["candidate_manifest_sha256"] == (
        "e81fc655f81ab43f1cfd5ad1b8644a9271a190027c49233efe89a2dd682c95f3"
    )
    assert projected["candidate_version"] == "phase12-candidate-v19"
    with pytest.raises(ValueError, match="custody"):
        attach_custody(base, git_sha="not-a-sha", candidate_manifest_sha256="e" * 64)


def test_canonical_qa_hard_v2_runs_all_twenty_four_once_without_gold_in_pipeline() -> None:
    assert _FROZEN_DATASET.is_file()
    assert hashlib.sha256(_FROZEN_DATASET.read_bytes()).hexdigest() == _FROZEN_SHA256
    dataset = load_dataset(_FROZEN_DATASET, allow_frozen=True)
    assert dataset["dataset_id"] == "qa_hard_v2"
    questions = dataset["queries"]
    assert len(questions) == 24
    qids = [row["qid"] for row in questions]
    assert len(qids) == len(set(qids))
    # capture_batch assigns cid-0..n over corpus; hops map relevant docs to those CIDs.
    corpus = dataset["corpus"]
    doc_to_index = {row["doc_id"]: index for index, row in enumerate(corpus)}

    class FrozenCLI(RecordingCLI):
        def eval_answer_batch(self, path: Path) -> dict[str, Any]:
            self.answer_rows = [json.loads(line) for line in path.read_text().splitlines()]
            results = []
            for question in questions:
                cids = [f"cid-{doc_to_index[doc_id]}" for doc_id in question["relevant_doc_ids"]]
                results.append(
                    {
                        "question_id": question["qid"],
                        "answer": question["gold_answer"],
                        "abstained": False,
                        "claims": [{"text": question["gold_answer"], "evidence_cids": cids[:1]}],
                        "hops": [
                            {
                                "index": 0,
                                "queries": [question["query"][:24]],
                                "channels": ["lexical"],
                                "retrieved_cids": cids[:1],
                            },
                            {
                                "index": 1,
                                "queries": ["bridge"],
                                "channels": ["graph"],
                                "retrieved_cids": cids,
                            },
                        ],
                        "reader": {"grounded_reader": {}, "query_decomposer": {}},
                    }
                )
            return {"results": results}

    cli = FrozenCLI()
    result = evaluate(dataset, cli)  # type: ignore[arg-type]
    assert result["trace_count"] == 24
    assert [trace["question_id"] for trace in result["traces"]] == qids
    assert result["qa"]["metrics"] == {"exact_match": 1.0, "token_f1": 1.0}
    assert result["qa"]["profile"] == "qa-em-f1-v1"
    assert "intervals" in result["qa"]
    assert result["retrieval"] == {"recall_at_5": 1.0, "ndcg_at_5": 1.0}
    assert result["grounding"]["second_hop"] == 24
    assert result["grounding"]["graph_participation"] == 24
    assert result["grounding"]["abstained"] == 0
    assert result["grounding"]["unsupported_claims"] == 0
    assert result["grounding"]["fabricated_citations"] == 0
    # Gold never crossed into public CLI payloads (only scorer used dataset gold).
    pipeline = json.dumps([cli.capture_rows, cli.answer_rows])
    assert "gold_answer" not in pipeline
    assert "gold_aliases" not in pipeline
    assert "relevant_doc_ids" not in pipeline
    assert "distractor_answer" not in pipeline
    assert len(cli.answer_rows) == 24
    assert [row["question_id"] for row in cli.answer_rows] == qids
    # Single-shot: evaluate processes the full frozen set; no per-qid patch surface.
    assert not hasattr(runner, "patch_question")
    assert not hasattr(runner, "rerun_question_ids")
    bound = attach_custody(
        result,
        git_sha=runner.PHASE12_V19_FREEZE["git_sha"],
        candidate_manifest_sha256=runner.PHASE12_V19_FREEZE["manifest_sha256"],
        candidate_version=runner.PHASE12_V19_FREEZE["candidate_version"],
    )
    assert bound["candidate_git_sha"] == runner.PHASE12_V19_FREEZE["git_sha"]
    assert bound["candidate_manifest_sha256"] == runner.PHASE12_V19_FREEZE["manifest_sha256"]


def test_evaluate_rejects_answer_order_drift_without_id_patch() -> None:
    """Failed order/identity must hard-fail; no silent reorder-by-qid patch path."""
    dataset = _dataset()
    dataset["queries"].append(
        {
            "qid": "q2",
            "query": "Who owns Helios?",
            "gold_answer": "Mara",
            "gold_aliases": ["Mara"],
            "relevant_doc_ids": ["d1"],
        }
    )

    class DriftCLI(RecordingCLI):
        def eval_answer_batch(self, path: Path) -> dict[str, Any]:
            self.answer_rows = [json.loads(line) for line in path.read_text().splitlines()]
            # Swapped question_id order relative to dataset queries.
            return {
                "results": [
                    {
                        "question_id": "q2",
                        "answer": "Mara",
                        "abstained": False,
                        "claims": [],
                        "hops": [],
                        "reader": {},
                    },
                    {
                        "question_id": "q1",
                        "answer": "Q3 2026",
                        "abstained": False,
                        "claims": [],
                        "hops": [],
                        "reader": {},
                    },
                ]
            }

    with pytest.raises(ValueError, match="order drift"):
        evaluate(dataset, DriftCLI())  # type: ignore[arg-type]


def test_answer_payloads_are_exactly_question_context_without_gold() -> None:
    """Capture/reader/decomposer JSONL is only tenant/user/question — never gold."""
    cli = RecordingCLI()
    evaluate(_dataset(), cli)  # type: ignore[arg-type]
    assert cli.answer_rows == [
        {
            "context": {"role": "reader", "tenant_id": "dev", "user_id": "dev-user"},
            "question": "When does Mara's project ship?",
            "question_id": "q1",
        }
    ]
    assert set(cli.answer_rows[0]) == {"context", "question", "question_id"}
    for row in cli.capture_rows:
        assert set(row) <= {
            "tenant",
            "user",
            "source_type",
            "source_identity",
            "content",
            "trust_tier",
        }
        assert "gold_answer" not in row
        assert "gold_aliases" not in row


def test_frozen_cli_one_shot_requires_execute_ledger_and_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protected frozen path fails closed without the full one-shot custody set."""
    store = tmp_path / "store"
    output = tmp_path / "out.json"
    manifest = tmp_path / "candidate.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_version": "phase12-candidate-v19",
                "git_sha": "df438ca34061467ecc227bcf4d45bb1f7e886aee",
            }
        )
    )
    # Avoid real clean-checkout / manifest validation side effects.
    monkeypatch.setattr(runner, "validate_candidate_manifest", lambda *a, **k: None)
    monkeypatch.setattr(runner, "require_clean_candidate_checkout", lambda *a, **k: None)

    with pytest.raises(ValueError, match="frozen execution requires"):
        runner.main(
            [
                "--dataset",
                str(_FROZEN_DATASET),
                "--candidate-manifest",
                str(manifest),
                "--store",
                str(store),
                "--output",
                str(output),
            ]
        )
    # execute-frozen without ledger/runtime/preflight still fails closed.
    with pytest.raises(ValueError, match="frozen execution requires"):
        runner.main(
            [
                "--dataset",
                str(_FROZEN_DATASET),
                "--candidate-manifest",
                str(manifest),
                "--store",
                str(store),
                "--output",
                str(output),
                "--execute-frozen",
            ]
        )
    # Non-canonical dataset may not use --execute-frozen.
    synth = tmp_path / "synth.json"
    synth.write_text(json.dumps(_dataset()))
    with pytest.raises(ValueError, match="restricted to canonical qa_hard_v2"):
        runner.main(
            [
                "--dataset",
                str(synth),
                "--candidate-manifest",
                str(manifest),
                "--store",
                str(store),
                "--output",
                str(output),
                "--execute-frozen",
            ]
        )


def test_no_per_question_id_patch_surface_on_runner_module() -> None:
    """A failed candidate must not expose per-QID patch/rerun helpers."""
    banned = (
        "patch_question",
        "rerun_question_ids",
        "patch_question_ids",
        "retry_failed_qids",
        "select_failed_questions",
    )
    for name in banned:
        assert not hasattr(runner, name)
    source = Path(runner.__file__).read_text(encoding="utf-8")
    for needle in (
        "patch_question",
        "rerun_question_ids",
        "per_question",
        "failed_qids",
    ):
        assert needle not in source
