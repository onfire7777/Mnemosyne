from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eval.public.adapters import hipporag_multihop

from eval.public.adapters.hipporag_multihop import (
    HippoRAGSchemaError,
    normalize,
    run,
    score_predictions,
)


def test_musique_normalizes_duplicate_titles_by_exact_text() -> None:
    value = {
        "assets": {
            "musique_corpus.json": [
                {"title": "Shared", "text": "first"},
                {"title": "Shared", "text": "second"},
            ],
            "musique.json": [
                {
                    "answer": "yes",
                    "answer_aliases": ["Yes"],
                    "id": "q1",
                    "paragraphs": [
                        {
                            "is_supporting": True,
                            "paragraph_text": "second",
                            "title": "Shared",
                        }
                    ],
                    "question": "Which one?",
                }
            ],
        }
    }
    benchmark = normalize(value)
    assert benchmark["dataset"] == "musique"
    assert benchmark["questions"][0]["gold_references"] == ["musique:p00001"]
    assert benchmark["questions"][0]["answers"] == ["yes", "Yes"]


@pytest.mark.parametrize(
    ("query_name", "dataset"),
    (("2wikimultihopqa.json", "2wiki"), ("hotpotqa.json", "hotpot")),
)
def test_title_support_schemas_normalize(query_name: str, dataset: str) -> None:
    value = {
        "assets": {
            query_name.replace(".json", "_corpus.json"): [
                {"title": "A", "text": "alpha"},
                {"title": "B", "text": "beta"},
            ],
            query_name: [
                {
                    "_id": "q",
                    "answer": "alpha",
                    "question": "What?",
                    "supporting_facts": [["A", 0], ["B", 1]],
                }
            ],
        }
    }
    benchmark = normalize(value)
    assert benchmark["dataset"] == dataset
    assert len(benchmark["questions"][0]["gold_references"]) == 2


def test_ambiguous_support_mapping_fails_closed() -> None:
    value = {
        "assets": {
            "hotpotqa_corpus.json": [
                {"title": "A", "text": "one"},
                {"title": "A", "text": "two"},
            ],
            "hotpotqa.json": [
                {
                    "_id": "q",
                    "answer": "x",
                    "question": "What?",
                    "supporting_facts": [["A", 0]],
                }
            ],
        }
    }
    with pytest.raises(HippoRAGSchemaError, match="uniquely"):
        normalize(value)


def test_prediction_scoring_is_standalone_and_deterministic() -> None:
    questions = [{"answers": ["The Red Fox", "red fox"], "question_id": "q"}]
    scored = score_predictions(questions, {"q": "red fox"})
    assert scored["family"] == "qa"
    assert scored["metrics"] == {"exact_match": 1.0, "token_f1": 1.0}
    with pytest.raises(HippoRAGSchemaError, match="missing prediction"):
        score_predictions(questions, {})


def test_retrieval_bundle_contract_has_no_qa_columns() -> None:
    source = Path(__file__).parents[1] / "eval/public/adapters/hipporag_multihop.py"
    text = source.read_text(encoding="utf-8")
    run_body = text.split("def run(", 1)[1].split("def normalize", 1)[0]
    assert "qa-em-f1" not in run_body
    assert "score_predictions" not in run_body
    assert hipporag_multihop._QUERY_SHARD_SIZE == 125


def test_adapter_uses_public_batch_search_and_explain() -> None:
    class FakeCLI:
        def capture_batch(self, path: Path) -> dict:
            import json

            rows = [json.loads(line) for line in path.read_text().splitlines()]
            return {
                "count": len(rows),
                "results": [{"cid": f"cid-{index}"} for index in range(len(rows))],
            }

        def search(self, tenant: str, question: str) -> dict:
            return {
                "hits": [{"id": "cid-0"}],
                "metadata": {"channel_scores": {"graph": 1.0}},
            }

        def explain(self, tenant: str, question: str) -> dict:
            return {"channels": ["graph_ppr"], "graph_backend": "local"}

    value = {
        "assets": {
            "hotpotqa_corpus.json": [{"title": "A", "text": "alpha"}],
            "hotpotqa.json": [
                {
                    "_id": "q",
                    "answer": "alpha",
                    "question": "What?",
                    "supporting_facts": [["A", 0]],
                }
            ],
        }
    }
    benchmark, traces, metrics = run(value, FakeCLI())
    assert benchmark["dataset"] == "hotpot"
    assert traces[0]["graph_evidence"]["observed"] is True
    assert metrics["metrics"] == {"recall_at_2": 1.0, "recall_at_5": 1.0}


def test_graph_evidence_requires_positive_graph_signal() -> None:
    empty = hipporag_multihop._graph_evidence(
        {"metadata": {"channel_scores": {}}},
        {"channels": [], "graph_backend": "configured"},
    )
    assert empty["observed"] is False
    positive = hipporag_multihop._graph_evidence(
        {"metadata": {"channel_scores": {"graph_ppr": 0.25}}}, {"channels": []}
    )
    assert positive["observed"] is True
    assert (
        hipporag_multihop._graph_evidence({}, {"channels": {"graph": 0}})["observed"]
        is False
    )
    assert (
        hipporag_multihop._graph_evidence({}, {"channels": {"graph": 1}})["observed"]
        is True
    )
    assert (
        hipporag_multihop._graph_evidence(
            {}, {"channels": {"graph": True, "ppr": float("inf")}}
        )["observed"]
        is False
    )
    assert (
        hipporag_multihop._graph_evidence(
            {"metadata": {"channel_scores": {"graph": float("inf")}}}, {}
        )["observed"]
        is False
    )


def test_duplicate_capture_cid_is_rejected() -> None:
    class DuplicateCIDCLI:
        def capture_batch(self, path: Path) -> dict[str, Any]:
            return {"results": [{"cid": "same"}, {"cid": "same"}]}

    value = {
        "assets": {
            "hotpotqa_corpus.json": [
                {"title": "A", "text": "alpha"},
                {"title": "B", "text": "beta"},
            ],
            "hotpotqa.json": [
                {
                    "_id": "q",
                    "answer": "alpha",
                    "question": "What?",
                    "supporting_facts": [["A", 0]],
                }
            ],
        }
    }
    with pytest.raises(HippoRAGSchemaError, match="duplicate CID"):
        run(value, DuplicateCIDCLI())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["questions"].append(dict(value["questions"][0])),
            "duplicate question",
        ),
        (
            lambda value: value["questions"][0].update(gold_references=["missing"]),
            "invalid gold",
        ),
        (
            lambda value: value["questions"][0].update(answers=[""]),
            "invalid answers",
        ),
    ],
)
def test_canonical_validation_rejects_ambiguous_data(
    mutation: Any, message: str
) -> None:
    value = {
        "assets": {
            "hotpotqa_corpus.json": [{"title": "A", "text": "alpha"}],
            "hotpotqa.json": [
                {
                    "_id": "q",
                    "answer": "alpha",
                    "question": "What?",
                    "supporting_facts": [["A", 0]],
                }
            ],
        }
    }
    benchmark = normalize(value)
    mutation(benchmark)
    with pytest.raises(HippoRAGSchemaError, match=message):
        hipporag_multihop._validate_canonical(benchmark)
